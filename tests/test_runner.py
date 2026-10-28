import asyncio
import uuid

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from resumecraft.core.enums import TaskStatus, TaskType
from resumecraft.db import models  # noqa: F401  (registers all models)
from resumecraft.db.base import Base
from resumecraft.db.models import Task
from resumecraft.db.repositories import task as task_repo
from resumecraft.worker.tasks._runner import TaskNotFoundError, run_task_flow


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _make_task(factory) -> uuid.UUID:
    async with factory() as session:
        task = Task(user_id=uuid.uuid4(), type=TaskType.PARSE_RESUME, input={})
        session.add(task)
        await session.commit()
        return task.id


async def _get_task(factory, task_id: uuid.UUID) -> Task:
    async with factory() as session:
        task = await task_repo.get_by_id(session, task_id)
        assert task is not None
        return task


async def test_flow_completes_task(session_factory) -> None:
    task_id = await _make_task(session_factory)

    async def work(session, task, update_progress) -> dict:
        await update_progress(0.5)
        return {"done": True}

    await run_task_flow(session_factory, task_id, work)
    task = await _get_task(session_factory, task_id)
    assert task.status == TaskStatus.COMPLETED
    assert task.result == {"done": True}
    assert task.progress == 0.5
    assert task.error is None


async def test_flow_marks_failed_on_error(session_factory) -> None:
    task_id = await _make_task(session_factory)

    async def work(session, task, update_progress) -> dict:
        raise ValueError("boom")

    await run_task_flow(session_factory, task_id, work)
    task = await _get_task(session_factory, task_id)
    assert task.status == TaskStatus.FAILED
    assert "boom" in (task.error or "")


async def test_flow_marks_failed_on_timeout(session_factory) -> None:
    task_id = await _make_task(session_factory)

    async def work(session, task, update_progress) -> dict:
        raise SoftTimeLimitExceeded()

    await run_task_flow(session_factory, task_id, work)
    task = await _get_task(session_factory, task_id)
    assert task.status == TaskStatus.FAILED
    assert "timed out" in (task.error or "")


async def test_flow_supports_concurrent_progress_callbacks(session_factory) -> None:
    task_id = await _make_task(session_factory)

    async def work(session, task, update_progress) -> dict:
        await asyncio.gather(update_progress(0.3), update_progress(0.6))
        return {"done": True}

    await run_task_flow(session_factory, task_id, work)
    task = await _get_task(session_factory, task_id)
    assert task.status == TaskStatus.COMPLETED
    assert task.progress in (0.3, 0.6)
    assert task.error is None


async def test_flow_marks_failed_after_concurrent_progress(session_factory) -> None:
    task_id = await _make_task(session_factory)

    async def work(session, task, update_progress) -> dict:
        await asyncio.gather(update_progress(0.3), update_progress(0.6))
        raise ValueError("boom")

    await run_task_flow(session_factory, task_id, work)
    task = await _get_task(session_factory, task_id)
    assert task.status == TaskStatus.FAILED
    assert "boom" in (task.error or "")


async def test_flow_raises_for_missing_task(session_factory) -> None:
    async def work(session, task, update_progress) -> dict:
        return {}

    with pytest.raises(TaskNotFoundError):
        await run_task_flow(session_factory, uuid.uuid4(), work)
