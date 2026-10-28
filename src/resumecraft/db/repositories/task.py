import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from resumecraft.core.enums import TaskStatus, TaskType
from resumecraft.db.models import Task


async def create(session: AsyncSession, task: Task) -> Task:
    session.add(task)
    await session.flush()
    await session.refresh(task)
    return task


async def get_by_id(session: AsyncSession, task_id: uuid.UUID) -> Task | None:
    result = await session.execute(select(Task).where(Task.id == task_id))
    return result.scalar_one_or_none()


async def get_by_id_for_user(
    session: AsyncSession, task_id: uuid.UUID, user_id: uuid.UUID
) -> Task | None:
    result = await session.execute(select(Task).where(Task.id == task_id, Task.user_id == user_id))
    return result.scalar_one_or_none()


async def get_latest_for_company(
    session: AsyncSession, company_id: uuid.UUID, user_id: uuid.UUID
) -> Task | None:
    """Newest research_company task whose input points at `company_id`."""
    result = await session.execute(
        select(Task)
        .where(
            Task.user_id == user_id,
            Task.type == TaskType.RESEARCH_COMPANY,
            Task.input["company_id"].as_string() == str(company_id),
        )
        .order_by(Task.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def set_celery_task_id(
    session: AsyncSession, task_id: uuid.UUID, celery_task_id: str
) -> None:
    task = await get_by_id(session, task_id)
    if task is None:
        raise LookupError(f"Task {task_id} not found")
    task.celery_task_id = celery_task_id
    await session.flush()


async def set_status(session: AsyncSession, task_id: uuid.UUID, status: TaskStatus) -> None:
    task = await get_by_id(session, task_id)
    if task is None:
        raise LookupError(f"Task {task_id} not found")
    task.status = status
    await session.flush()


async def set_progress(session: AsyncSession, task_id: uuid.UUID, progress: float) -> None:
    task = await get_by_id(session, task_id)
    if task is None:
        raise LookupError(f"Task {task_id} not found")
    task.progress = progress
    await session.flush()


async def set_result(session: AsyncSession, task_id: uuid.UUID, result: dict) -> None:
    task = await get_by_id(session, task_id)
    if task is None:
        raise LookupError(f"Task {task_id} not found")
    task.result = result
    await session.flush()


async def set_error(session: AsyncSession, task_id: uuid.UUID, error: str) -> None:
    task = await get_by_id(session, task_id)
    if task is None:
        raise LookupError(f"Task {task_id} not found")
    task.error = error
    await session.flush()
