import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from resumecraft.core.enums import TaskType
from resumecraft.core.exceptions import NotFoundError
from resumecraft.db.models import Task
from resumecraft.db.repositories import task as task_repo


async def create_parse_task(session: AsyncSession, user_id: uuid.UUID, input_data: dict) -> Task:
    task = Task(user_id=user_id, type=TaskType.PARSE_RESUME, input=input_data)
    await task_repo.create(session, task)
    await session.commit()
    return task


async def create_research_task(session: AsyncSession, user_id: uuid.UUID, input_data: dict) -> Task:
    task = Task(user_id=user_id, type=TaskType.RESEARCH_COMPANY, input=input_data)
    await task_repo.create(session, task)
    await session.commit()
    return task


async def attach_celery_task_id(
    session: AsyncSession, task_id: uuid.UUID, celery_task_id: str
) -> None:
    await task_repo.set_celery_task_id(session, task_id, celery_task_id)
    await session.commit()


async def get_task_for_user(session: AsyncSession, task_id: uuid.UUID, user_id: uuid.UUID) -> Task:
    task = await task_repo.get_by_id_for_user(session, task_id, user_id)
    if task is None:
        raise NotFoundError("task", task_id)
    return task
