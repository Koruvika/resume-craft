import uuid

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from resumecraft.core.enums import JobStatus, JobType
from resumecraft.db import models  # noqa: F401  (registers all models)
from resumecraft.db.base import Base
from resumecraft.db.models import Job
from resumecraft.db.repositories import job as job_repo
from resumecraft.worker.tasks._runner import JobNotFoundError, run_job_flow


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _make_job(factory) -> uuid.UUID:
    async with factory() as session:
        job = Job(user_id=uuid.uuid4(), type=JobType.GENERATE_RESUME, input={})
        session.add(job)
        await session.commit()
        return job.id


async def _get_job(factory, job_id: uuid.UUID) -> Job:
    async with factory() as session:
        job = await job_repo.get_by_id(session, job_id)
        assert job is not None
        return job


async def test_flow_completes_job(session_factory) -> None:
    job_id = await _make_job(session_factory)

    async def work(session, job, update_progress) -> dict:
        await update_progress(0.5)
        return {"done": True}

    await run_job_flow(session_factory, job_id, work)
    job = await _get_job(session_factory, job_id)
    assert job.status == JobStatus.COMPLETED
    assert job.result == {"done": True}
    assert job.progress == 0.5
    assert job.error is None


async def test_flow_marks_failed_on_error(session_factory) -> None:
    job_id = await _make_job(session_factory)

    async def work(session, job, update_progress) -> dict:
        raise ValueError("boom")

    await run_job_flow(session_factory, job_id, work)
    job = await _get_job(session_factory, job_id)
    assert job.status == JobStatus.FAILED
    assert "boom" in (job.error or "")


async def test_flow_marks_failed_on_timeout(session_factory) -> None:
    job_id = await _make_job(session_factory)

    async def work(session, job, update_progress) -> dict:
        raise SoftTimeLimitExceeded()

    await run_job_flow(session_factory, job_id, work)
    job = await _get_job(session_factory, job_id)
    assert job.status == JobStatus.FAILED
    assert "timed out" in (job.error or "")


async def test_flow_raises_for_missing_job(session_factory) -> None:
    async def work(session, job, update_progress) -> dict:
        return {}

    with pytest.raises(JobNotFoundError):
        await run_job_flow(session_factory, uuid.uuid4(), work)
