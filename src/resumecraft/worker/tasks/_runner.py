import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from resumecraft.core.config import get_settings
from resumecraft.core.enums import JobStatus
from resumecraft.db.models import Job
from resumecraft.db.repositories import job as job_repo

logger = structlog.get_logger(__name__)

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
            # Work coroutines may run concurrently (e.g. asyncio.gather in
            # company research), so progress writes must not share the work
            # session: an AsyncSession is not safe for concurrent use.
            async with session_factory() as progress_session:
                await job_repo.set_progress(progress_session, job_id, progress)
                await progress_session.commit()

        await job_repo.set_status(session, job_id, JobStatus.RUNNING)
        await session.commit()
        try:
            result = await work(session, job, update_progress)
            await job_repo.set_result(session, job_id, result)
            await job_repo.set_status(session, job_id, JobStatus.COMPLETED)
            await session.commit()
        except SoftTimeLimitExceeded:
            # A fresh session marks the failure: the work session may be in
            # an unusable state when the task times out mid-operation.
            await session.rollback()
            async with session_factory() as fail_session:
                await job_repo.set_error(fail_session, job_id, "Task timed out")
                await job_repo.set_status(fail_session, job_id, JobStatus.FAILED)
                await fail_session.commit()
        except Exception as exc:
            # Swallow after recording: the Job row carries the failure, so a
            # re-raise would only trigger a costly blind autoretry. Log the
            # full stack — the row keeps only the summary message.
            # A fresh session marks the failure: the work session may have
            # been poisoned by whatever crashed the work function.
            logger.exception("job_failed", job_id=job_id, error=str(exc))
            await session.rollback()
            async with session_factory() as fail_session:
                await job_repo.set_error(fail_session, job_id, str(exc))
                await job_repo.set_status(fail_session, job_id, JobStatus.FAILED)
                await fail_session.commit()


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
