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


async def test_upload_file_accepts_json_asynchronously(client, db_session) -> None:
    response = await _upload_file(client, content=FILE_PAYLOAD)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"

    resume = (await db_session.execute(select(Resume))).scalars().one()
    assert resume.id == uuid.UUID(body["resume_id"])
    assert resume.status.value == "pending"
    assert resume.content is None

    job = await job_repo.get_by_id(db_session, uuid.UUID(body["job_id"]))
    assert job is not None
    assert job.celery_task_id == "fake-task-id"
    assert job.input["resume_id"] == str(resume.id)
    assert job.input["source_type"] == "json"
    assert job.input["file_b64"]


async def test_upload_file_accepts_pdf_asynchronously(client, db_session) -> None:
    response = await _upload_file(
        client, content=b"%PDF-fake", filename="resume.pdf", content_type="application/pdf"
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"

    resume = (await db_session.execute(select(Resume))).scalars().one()
    assert resume.content is None
    assert resume.title == "resume"
    job = await job_repo.get_by_id(db_session, uuid.UUID(body["job_id"]))
    assert job is not None
    assert job.input["source_type"] == "pdf"
    assert job.input["filename"] == "resume.pdf"


async def test_upload_file_accepts_custom_title(client, db_session) -> None:
    response = await _upload_file(client, content=FILE_PAYLOAD, title="Custom title")
    assert response.status_code == 202
    resume = (await db_session.execute(select(Resume))).scalars().one()
    assert resume.title == "Custom title"


async def test_upload_file_rejects_wrong_content_type(client) -> None:
    response = await _upload_file(client, content=FILE_PAYLOAD, content_type="text/plain")
    assert response.status_code == 422
    assert "application/json" in response.json()["error"]["message"]
    assert "application/pdf" in response.json()["error"]["message"]


async def test_upload_file_rejects_missing_file(client) -> None:
    response = await client.post("/api/v1/resumes/upload-file")
    assert response.status_code == 422


async def test_upload_file_rejects_oversize_json(client, monkeypatch) -> None:
    monkeypatch.setattr(resume_service, "MAX_UPLOAD_BYTES", 10)
    response = await _upload_file(client, content=b"x" * 11)
    assert response.status_code == 413


async def test_upload_file_rejects_oversize_pdf(client, monkeypatch) -> None:
    monkeypatch.setattr(resume_service, "MAX_PDF_UPLOAD_BYTES", 10)
    response = await _upload_file(
        client, content=b"x" * 11, filename="resume.pdf", content_type="application/pdf"
    )
    assert response.status_code == 413


async def test_get_resume_returns_status(client) -> None:
    upload = await _upload_file(client, content=FILE_PAYLOAD)
    resume_id = upload.json()["resume_id"]

    response = await client.get(f"/api/v1/resumes/{resume_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == resume_id
    assert body["status"] == "pending"
    assert body["content"] is None


async def test_get_resume_returns_completed_content(client, db_session) -> None:
    from resumecraft.core.enums import ResumeStatus

    upload = await _upload_file(client, content=FILE_PAYLOAD)
    resume_id = upload.json()["resume_id"]
    resume = (await db_session.execute(select(Resume))).scalars().one()
    resume.status = ResumeStatus.COMPLETED
    resume.content = UPLOAD_JSON["resume_json"]
    await db_session.commit()

    response = await client.get(f"/api/v1/resumes/{resume_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["content"]["contact_info"]["full_name"] == "Jane Doe"


async def test_get_resume_unknown_returns_404(client) -> None:
    response = await client.get(f"/api/v1/resumes/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "resume_not_found"


async def test_get_resume_requires_auth(db_session) -> None:
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get(f"/api/v1/resumes/{uuid.uuid4()}")
    assert response.status_code == 401


async def _render_pdf(client, resume_id, *, theme=None, locale=None):
    params = {}
    if theme is not None:
        params["theme"] = theme
    if locale is not None:
        params["locale"] = locale
    return await client.get(f"/api/v1/resumes/{resume_id}/pdf", params=params)


async def test_render_resume_pdf_returns_pdf(client, db_session, monkeypatch) -> None:
    def fake_generate(model, filename):
        return b"%PDF-1.4 fake", filename

    monkeypatch.setattr("resumecraft.services.render_service.generate_pdf_bytes", fake_generate)

    response = await client.post("/api/v1/resumes/upload", json=UPLOAD_JSON)
    resume_id = response.json()["id"]

    response = await _render_pdf(client, resume_id)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == f'inline; filename="resume-{resume_id}.pdf"'
    assert response.content == b"%PDF-1.4 fake"


async def test_render_resume_pdf_requires_auth(db_session, monkeypatch) -> None:
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get(f"/api/v1/resumes/{uuid.uuid4()}/pdf")
    assert response.status_code == 401


async def test_render_resume_pdf_unknown_resume(client) -> None:
    response = await _render_pdf(client, uuid.uuid4())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "resume_not_found"


async def test_render_resume_pdf_rejects_unknown_theme(client) -> None:
    response = await _render_pdf(client, uuid.uuid4(), theme="nope")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_render_option"


async def test_render_resume_pdf_rejects_unknown_locale(client) -> None:
    response = await _render_pdf(client, uuid.uuid4(), locale="klingon")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_render_option"


async def test_render_resume_pdf_rejects_pending_resume(client, db_session, monkeypatch) -> None:
    upload = await _upload_file(client, content=FILE_PAYLOAD)
    resume_id = upload.json()["resume_id"]

    response = await _render_pdf(client, resume_id)
    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "resume_not_ready"
    assert body["details"]["status"] == "pending"
