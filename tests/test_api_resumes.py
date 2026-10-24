import json
import uuid

import httpx
from httpx import ASGITransport
from sqlalchemy import select

from resumecraft.db.models import Resume
from resumecraft.db.repositories import job as job_repo
from resumecraft.db.session import get_session
from resumecraft.main import create_app
from resumecraft.services import resume_service

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


async def test_upload_json_creates_resume_immediately(client, db_session) -> None:
    response = await client.post("/api/v1/resumes/upload", json=UPLOAD_JSON)
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Staff Engineer"
    assert body["content"]["contact_info"]["full_name"] == "Jane Doe"

    result = await db_session.execute(select(Resume))
    assert len(result.scalars().all()) == 1


async def test_upload_rejects_invalid_resume_json(client) -> None:
    response = await client.post(
        "/api/v1/resumes/upload",
        json={"resume_json": {"contact_info": "not-a-contact-info"}},
    )
    assert response.status_code == 422


async def test_upload_accepts_custom_title(client, db_session) -> None:
    payload = {**UPLOAD_JSON, "title": "My custom title"}
    response = await client.post("/api/v1/resumes/upload", json=payload)
    assert response.status_code == 201
    assert response.json()["title"] == "My custom title"


async def test_upload_rejects_blank_title(client) -> None:
    payload = {**UPLOAD_JSON, "title": ""}
    response = await client.post("/api/v1/resumes/upload", json=payload)
    assert response.status_code == 422


async def test_upload_requires_resume_json(client) -> None:
    response = await client.post("/api/v1/resumes/upload", json={})
    assert response.status_code == 422


async def test_upload_requires_auth(db_session, monkeypatch) -> None:
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.post("/api/v1/resumes/upload", json=UPLOAD_JSON)
    assert response.status_code == 401


FILE_PAYLOAD = json.dumps(UPLOAD_JSON["resume_json"]).encode()


async def _upload_file(
    client, *, content: bytes, filename="resume.json", content_type="application/json", title=None
):
    data = {} if title is None else {"title": title}
    return await client.post(
        "/api/v1/resumes/upload-file",
        files={"file": (filename, content, content_type)},
        data=data,
    )


async def test_upload_file_creates_resume(client, db_session) -> None:
    response = await _upload_file(client, content=FILE_PAYLOAD)
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Staff Engineer"
    assert body["content"]["contact_info"]["full_name"] == "Jane Doe"

    result = await db_session.execute(select(Resume))
    assert len(result.scalars().all()) == 1


async def test_upload_file_accepts_custom_title(client) -> None:
    response = await _upload_file(client, content=FILE_PAYLOAD, title="Custom title")
    assert response.status_code == 201
    assert response.json()["title"] == "Custom title"


async def test_upload_file_rejects_wrong_content_type(client) -> None:
    response = await _upload_file(client, content=FILE_PAYLOAD, content_type="text/plain")
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "File must be application/json"


async def test_upload_file_rejects_invalid_json(client) -> None:
    response = await _upload_file(client, content=b"{not json")
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "File is not valid JSON"


async def test_upload_file_rejects_schema_violation(client) -> None:
    bad = json.dumps({"languages": [{"language": "English", "level": "nine"}]}).encode()
    response = await _upload_file(client, content=bad)
    assert response.status_code == 422
    assert response.json()["error"]["message"]


async def test_upload_file_rejects_missing_file(client) -> None:
    response = await client.post("/api/v1/resumes/upload-file")
    assert response.status_code == 422


async def test_upload_file_rejects_oversize(client, monkeypatch) -> None:
    monkeypatch.setattr(resume_service, "MAX_UPLOAD_BYTES", 10)
    response = await _upload_file(client, content=b"x" * 11)
    assert response.status_code == 413
