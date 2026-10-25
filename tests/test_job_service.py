import uuid

import pytest

from resumecraft.core.enums import JobStatus, JobType
from resumecraft.core.exceptions import NotFoundError
from resumecraft.db.repositories import job as job_repo
from resumecraft.services import job_service


async def test_create_and_fetch_parse_job(db_session) -> None:
    user_id = uuid.uuid4()
    job = await job_service.create_parse_job(db_session, user_id, {"resume_id": "...", "a": 1})
    assert job.status == JobStatus.PENDING
    assert job.type == JobType.PARSE_RESUME
    assert job.progress == 0.0

    fetched = await job_service.get_job_for_user(db_session, job.id, user_id)
    assert fetched.id == job.id
    assert fetched.input == {"resume_id": "...", "a": 1}


async def test_get_job_for_user_scopes_by_user(db_session) -> None:
    job = await job_service.create_parse_job(db_session, uuid.uuid4(), {"a": 1})
    other_user = uuid.uuid4()
    with pytest.raises(NotFoundError) as exc_info:
        await job_service.get_job_for_user(db_session, job.id, other_user)
    assert exc_info.value.code == "job_not_found"


async def test_attach_task_id(db_session) -> None:
    job = await job_service.create_parse_job(db_session, uuid.uuid4(), {"a": 1})
    await job_service.attach_task_id(db_session, job.id, "task-123")
    fetched = await job_repo.get_by_id(db_session, job.id)
    assert fetched is not None
    assert fetched.celery_task_id == "task-123"
