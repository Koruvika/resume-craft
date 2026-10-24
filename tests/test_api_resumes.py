import uuid

import httpx
from httpx import ASGITransport
from sqlalchemy import select

from resumecraft.core.enums import JobType
from resumecraft.db.models import Resume
from resumecraft.db.repositories import job as job_repo
from resumecraft.db.session import get_session
from resumecraft.main import create_app

VALID_PAYLOAD = {"resume_text": "x" * 60, "target_role": "Backend Engineer"}


async def test_generate_resume_accepted(client, db_session) -> None:
    response = await client.post("/api/v1/resumes/generate", json=VALID_PAYLOAD)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"

    job_id = uuid.UUID(body["job_id"])
    job = await job_repo.get_by_id(db_session, job_id)
    assert job is not None
    assert job.celery_task_id == "fake-task-id"
    assert job.input == VALID_PAYLOAD


async def test_generate_resume_rejects_short_text(client) -> None:
    response = await client.post(
        "/api/v1/resumes/generate", json={"resume_text": "short", "target_role": "x"}
    )
    assert response.status_code == 422


async def test_generate_resume_requires_auth(db_session, monkeypatch) -> None:
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.post("/api/v1/resumes/generate", json=VALID_PAYLOAD)
    assert response.status_code == 401


UPLOAD_JSON = {
    "resume_json": {
        "contact_info": {"full_name": "Jane Doe", "headline": "Staff Engineer"},
        "summary": "Did things",
        "skills": {"groups": [{"category": "Languages", "skills": ["python"]}]},
    }
}
UPLOAD_TEXT = {"resume_text": "x" * 60}


async def test_upload_json_creates_resume_immediately(client, db_session) -> None:
    response = await client.post("/api/v1/resumes/upload", json=UPLOAD_JSON)
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Staff Engineer"
    assert body["content"]["contact_info"]["full_name"] == "Jane Doe"

    result = await db_session.execute(select(Resume))
    assert len(result.scalars().all()) == 1


async def test_upload_text_enqueues_parse_job(client, db_session) -> None:
    response = await client.post("/api/v1/resumes/upload", json=UPLOAD_TEXT)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"

    job = await job_repo.get_by_id(db_session, uuid.UUID(body["job_id"]))
    assert job is not None
    assert job.type == JobType.PARSE_RESUME
    assert job.celery_task_id == "fake-task-id"
    assert job.input == {"resume_text": "x" * 60}


async def test_upload_requires_exactly_one_source(client) -> None:
    both = {**UPLOAD_JSON, **UPLOAD_TEXT}
    assert (await client.post("/api/v1/resumes/upload", json=both)).status_code == 422
    assert (await client.post("/api/v1/resumes/upload", json={})).status_code == 422


async def test_upload_rejects_short_text(client) -> None:
    response = await client.post("/api/v1/resumes/upload", json={"resume_text": "short"})
    assert response.status_code == 422


async def test_upload_requires_auth(db_session, monkeypatch) -> None:
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.post("/api/v1/resumes/upload", json=UPLOAD_TEXT)
    assert response.status_code == 401
