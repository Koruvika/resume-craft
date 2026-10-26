import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from resumecraft.core.enums import JobStatus, JobType
from resumecraft.db.models import Job


async def create(session: AsyncSession, job: Job) -> Job:
    session.add(job)
    await session.flush()
    await session.refresh(job)
    return job


async def get_by_id(session: AsyncSession, job_id: uuid.UUID) -> Job | None:
    result = await session.execute(select(Job).where(Job.id == job_id))
    return result.scalar_one_or_none()


async def get_by_id_for_user(
    session: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID
) -> Job | None:
    result = await session.execute(select(Job).where(Job.id == job_id, Job.user_id == user_id))
    return result.scalar_one_or_none()


async def get_latest_for_research(
    session: AsyncSession, research_id: uuid.UUID, user_id: uuid.UUID
) -> Job | None:
    """Newest company_research job whose input points at `research_id`."""
    result = await session.execute(
        select(Job)
        .where(
            Job.user_id == user_id,
            Job.type == JobType.COMPANY_RESEARCH,
            Job.input["research_id"].as_string() == str(research_id),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def set_celery_task_id(session: AsyncSession, job_id: uuid.UUID, celery_task_id: str) -> None:
    job = await get_by_id(session, job_id)
    if job is None:
        raise LookupError(f"Job {job_id} not found")
    job.celery_task_id = celery_task_id
    await session.flush()


async def set_status(session: AsyncSession, job_id: uuid.UUID, status: JobStatus) -> None:
    job = await get_by_id(session, job_id)
    if job is None:
        raise LookupError(f"Job {job_id} not found")
    job.status = status
    await session.flush()


async def set_progress(session: AsyncSession, job_id: uuid.UUID, progress: float) -> None:
    job = await get_by_id(session, job_id)
    if job is None:
        raise LookupError(f"Job {job_id} not found")
    job.progress = progress
    await session.flush()


async def set_result(session: AsyncSession, job_id: uuid.UUID, result: dict) -> None:
    job = await get_by_id(session, job_id)
    if job is None:
        raise LookupError(f"Job {job_id} not found")
    job.result = result
    await session.flush()


async def set_error(session: AsyncSession, job_id: uuid.UUID, error: str) -> None:
    job = await get_by_id(session, job_id)
    if job is None:
        raise LookupError(f"Job {job_id} not found")
    job.error = error
    await session.flush()
