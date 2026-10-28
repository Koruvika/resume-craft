import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from resumecraft.core.config import get_settings
from resumecraft.core.enums import TaskStatus
from resumecraft.db.models import Task
from resumecraft.db.repositories import task as task_repo

logger = structlog.get_logger(__name__)

ProgressFn = Callable[[float], Awaitable[None]]
WorkFn = Callable[[AsyncSession, Task, ProgressFn], Awaitable[dict[str, Any]]]


class TaskNotFoundError(Exception):
    def __init__(self, task_id: uuid.UUID) -> None:
        super().__init__(f"Task {task_id} not found")


async def run_task_flow(
    session_factory: async_sessionmaker[AsyncSession],
    task_id: uuid.UUID,
    work: WorkFn,
) -> None:
    """Task lifecycle: PENDING -> RUNNING -> COMPLETED/FAILED, with progress callbacks."""
    async with session_factory() as session:
        task = await task_repo.get_by_id(session, task_id)
        if task is None:
            raise TaskNotFoundError(task_id)

        async def update_progress(progress: float) -> None:
            # Work coroutines may run concurrently (e.g. asyncio.gather in
            # company research), so progress writes must not share the work
            # session: an AsyncSession is not safe for concurrent use.
            async with session_factory() as progress_session:
                await task_repo.set_progress(progress_session, task_id, progress)
                await progress_session.commit()

        await task_repo.set_status(session, task_id, TaskStatus.RUNNING)
        await session.commit()
        try:
            result = await work(session, task, update_progress)
            await task_repo.set_result(session, task_id, result)
            await task_repo.set_status(session, task_id, TaskStatus.COMPLETED)
            await session.commit()
        except SoftTimeLimitExceeded:
            # A fresh session marks the failure: the work session may be in
            # an unusable state when the task times out mid-operation.
            await session.rollback()
            async with session_factory() as fail_session:
                await task_repo.set_error(fail_session, task_id, "Task timed out")
                await task_repo.set_status(fail_session, task_id, TaskStatus.FAILED)
                await fail_session.commit()
        except Exception as exc:
            # Swallow after recording: the Task row carries the failure, so a
            # re-raise would only trigger a costly blind autoretry. Log the
            # full stack — the row keeps only the summary message.
            # A fresh session marks the failure: the work session may have
            # been poisoned by whatever crashed the work function.
            logger.exception("task_failed", task_id=task_id, error=str(exc))
            await session.rollback()
            async with session_factory() as fail_session:
                await task_repo.set_error(fail_session, task_id, str(exc))
                await task_repo.set_status(fail_session, task_id, TaskStatus.FAILED)
                await fail_session.commit()


def run_task(task_id: str, work: WorkFn) -> None:
    """Celery task entry: fresh engine per invocation (Hodai pattern), disposed after."""
    asyncio.run(_run_task(uuid.UUID(task_id), work))


async def _run_task(task_id: uuid.UUID, work: WorkFn) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await run_task_flow(session_factory, task_id, work)
    finally:
        await engine.dispose()
