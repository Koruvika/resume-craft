import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from resumecraft.core.config import get_settings
from resumecraft.core.enums import JobStatus
from resumecraft.db.models import Job
from resumecraft.db.repositories import job as job_repo

ProgressFn = Callable[[float], Awaitable[None]]
WorkFn = Callable[[AsyncSession, Job, ProgressFn], Awaitable[dict[str, Any]]]


class JobNotFoundError(Exception):
    def __init__(self, job_id: uuid.UUID) -> None:
        super().__init__(f"Job {job_id} not found")


async def run_job_flow(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    work: WorkFn,
) -> None:
    """Job lifecycle: PENDING -> RUNNING -> COMPLETED/FAILED, with progress callbacks."""
    async with session_factory() as session:
        job = await job_repo.get_by_id(session, job_id)
        if job is None:
            raise JobNotFoundError(job_id)

        async def update_progress(progress: float) -> None:
            await job_repo.set_progress(session, job.id, progress)
            await session.commit()

        await job_repo.set_status(session, job.id, JobStatus.RUNNING)
        await session.commit()
        try:
            result = await work(session, job, update_progress)
            await job_repo.set_result(session, job.id, result)
            await job_repo.set_status(session, job.id, JobStatus.COMPLETED)
            await session.commit()
        except SoftTimeLimitExceeded:
            await session.rollback()
            await job_repo.set_error(session, job.id, "Task timed out")
            await job_repo.set_status(session, job.id, JobStatus.FAILED)
            await session.commit()
        except Exception as exc:
            # Swallow after recording: the Job row carries the failure, so a
            # re-raise would only trigger a costly blind autoretry.
            await session.rollback()
            await job_repo.set_error(session, job.id, str(exc))
            await job_repo.set_status(session, job.id, JobStatus.FAILED)
            await session.commit()


def run_job_task(job_id: str, work: WorkFn) -> None:
    """Celery task entry: fresh engine per invocation (Hodai pattern), disposed after."""
    asyncio.run(_run_job_task(uuid.UUID(job_id), work))


async def _run_job_task(job_id: uuid.UUID, work: WorkFn) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await run_job_flow(session_factory, job_id, work)
    finally:
        await engine.dispose()
