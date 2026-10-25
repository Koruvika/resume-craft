import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from resumecraft.core.enums import JobType
from resumecraft.core.exceptions import NotFoundError
from resumecraft.db.models import Job
from resumecraft.db.repositories import job as job_repo


async def create_parse_job(session: AsyncSession, user_id: uuid.UUID, input_data: dict) -> Job:
    job = Job(user_id=user_id, type=JobType.PARSE_RESUME, input=input_data)
    await job_repo.create(session, job)
    await session.commit()
    return job


async def attach_task_id(session: AsyncSession, job_id: uuid.UUID, celery_task_id: str) -> None:
    await job_repo.set_celery_task_id(session, job_id, celery_task_id)
    await session.commit()


async def get_job_for_user(session: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID) -> Job:
    job = await job_repo.get_by_id_for_user(session, job_id, user_id)
    if job is None:
        raise NotFoundError("job", job_id)
    return job
