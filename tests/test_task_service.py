import uuid

import pytest

from resumecraft.core.enums import TaskStatus, TaskType
from resumecraft.core.exceptions import NotFoundError
from resumecraft.db.repositories import task as task_repo
from resumecraft.services import task_service


async def test_create_and_fetch_parse_task(db_session) -> None:
    user_id = uuid.uuid4()
    task = await task_service.create_parse_task(db_session, user_id, {"resume_id": "...", "a": 1})
    assert task.status == TaskStatus.PENDING
    assert task.type == TaskType.PARSE_RESUME
    assert task.progress == 0.0

    fetched = await task_service.get_task_for_user(db_session, task.id, user_id)
    assert fetched.id == task.id
    assert fetched.input == {"resume_id": "...", "a": 1}


async def test_get_task_for_user_scopes_by_user(db_session) -> None:
    task = await task_service.create_parse_task(db_session, uuid.uuid4(), {"a": 1})
    other_user = uuid.uuid4()
    with pytest.raises(NotFoundError) as exc_info:
        await task_service.get_task_for_user(db_session, task.id, other_user)
    assert exc_info.value.code == "task_not_found"


async def test_attach_celery_task_id(db_session) -> None:
    task = await task_service.create_parse_task(db_session, uuid.uuid4(), {"a": 1})
    await task_service.attach_celery_task_id(db_session, task.id, "task-123")
    fetched = await task_repo.get_by_id(db_session, task.id)
    assert fetched is not None
    assert fetched.celery_task_id == "task-123"
