import json
import uuid
from datetime import UTC, datetime

import httpx
from httpx import ASGITransport
from sqlalchemy import select

from conftest import TEST_USER_ID
from resumecraft.core.enums import ResumeStatus
from resumecraft.db.models import Resume
from resumecraft.db.repositories import task as task_repo
from resumecraft.db.session import get_session
from resumecraft.main import create_app
from resumecraft.services import resume_service

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

    task = await task_repo.get_by_id(db_session, uuid.UUID(body["task_id"]))
    assert task is not None
    assert task.celery_task_id == "fake-task-id"
    assert task.input["resume_id"] == str(resume.id)
    assert task.input["source_type"] == "json"
    assert task.input["file_b64"]


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
    task = await task_repo.get_by_id(db_session, uuid.UUID(body["task_id"]))
    assert task is not None
    assert task.input["source_type"] == "pdf"
    assert task.input["filename"] == "resume.pdf"


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


async def _seed(
    db_session,
    user_id,
    *,
    title: str,
    created_at,
    pending: bool = False,
) -> Resume:
    resume = Resume(
        user_id=user_id,
        title=title,
        content=None if pending else {"summary": "seed"},
        status=ResumeStatus.PENDING if pending else ResumeStatus.COMPLETED,
        created_at=created_at,
    )
    db_session.add(resume)
    await db_session.commit()
    return resume


async def test_list_resumes_returns_newest_first_summary_envelope(client, db_session) -> None:
    older = await _seed(
        db_session,
        TEST_USER_ID,
        title="Older",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    newer = await _seed(
        db_session,
        TEST_USER_ID,
        title="Newer",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    response = await client.get("/api/v1/resumes")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert [item["id"] for item in body["items"]] == [str(newer.id), str(older.id)]
    assert set(body["items"][0]) == {
        "id",
        "title",
        "status",
        "error",
        "created_at",
        "updated_at",
    }


async def test_list_resumes_pagination_and_search(client, db_session) -> None:
    await _seed(
        db_session,
        TEST_USER_ID,
        title="Backend",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    await _seed(
        db_session,
        TEST_USER_ID,
        title="Frontend",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    response = await client.get("/api/v1/resumes", params={"limit": 1, "offset": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["title"] for item in body["items"]] == ["Backend"]

    response = await client.get("/api/v1/resumes", params={"search": "BACKEND"})
    body = response.json()
    assert body["total"] == 1
    assert [item["title"] for item in body["items"]] == ["Backend"]


async def test_list_resumes_excludes_other_users_and_deleted(client, db_session) -> None:
    await _seed(
        db_session,
        uuid.uuid4(),
        title="Not mine",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    mine = await _seed(
        db_session, TEST_USER_ID, title="Mine", created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    await resume_service.soft_delete_resume(db_session, TEST_USER_ID, mine.id)

    response = await client.get("/api/v1/resumes")

    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_list_resumes_requires_auth(db_session) -> None:
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get("/api/v1/resumes")
    assert response.status_code == 401


async def test_update_resume_title_and_content(client, db_session) -> None:
    resume = await _seed(
        db_session,
        TEST_USER_ID,
        title="Before",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    response = await client.patch(
        f"/api/v1/resumes/{resume.id}",
        json={"title": "After", "content": UPLOAD_JSON["resume_json"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "After"
    assert body["content"]["contact_info"]["full_name"] == "Jane Doe"
    assert body["status"] == "completed"


async def test_update_resume_content_only(client, db_session) -> None:
    resume = await _seed(
        db_session, TEST_USER_ID, title="Keep", created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    response = await client.patch(
        f"/api/v1/resumes/{resume.id}", json={"content": UPLOAD_JSON["resume_json"]}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Keep"
    assert body["content"]["summary"] == "Did things"


async def test_update_resume_content_rejected_when_pending(client, db_session) -> None:
    resume = await _seed(
        db_session,
        TEST_USER_ID,
        title="Pending",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        pending=True,
    )

    response = await client.patch(
        f"/api/v1/resumes/{resume.id}", json={"content": UPLOAD_JSON["resume_json"]}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "resume_not_ready"

    response = await client.patch(f"/api/v1/resumes/{resume.id}", json={"title": "Retitled"})
    assert response.status_code == 200
    assert response.json()["title"] == "Retitled"


async def test_update_resume_unknown_id_is_404(client) -> None:
    response = await client.patch(f"/api/v1/resumes/{uuid.uuid4()}", json={"title": "Ghost"})
    assert response.status_code == 404


async def test_update_resume_rejects_empty_and_blank(client, db_session) -> None:
    resume = await _seed(
        db_session,
        TEST_USER_ID,
        title="Valid",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    response = await client.patch(f"/api/v1/resumes/{resume.id}", json={})
    assert response.status_code == 422

    response = await client.patch(f"/api/v1/resumes/{resume.id}", json={"title": ""})
    assert response.status_code == 422


async def test_update_resume_requires_auth(db_session) -> None:
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.patch(f"/api/v1/resumes/{uuid.uuid4()}", json={"title": "Nope"})
    assert response.status_code == 401


async def test_delete_resume_soft_deletes_then_404s_everywhere(client, db_session) -> None:
    resume = await _seed(
        db_session,
        TEST_USER_ID,
        title="Doomed",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    response = await client.delete(f"/api/v1/resumes/{resume.id}")
    assert response.status_code == 204
    assert response.content == b""

    assert (await client.get(f"/api/v1/resumes/{resume.id}")).status_code == 404
    assert (await client.get(f"/api/v1/resumes/{resume.id}/pdf")).status_code == 404
    assert (
        await client.patch(f"/api/v1/resumes/{resume.id}", json={"title": "Z"})
    ).status_code == 404
    assert (await client.delete(f"/api/v1/resumes/{resume.id}")).status_code == 404
    assert (await client.get("/api/v1/resumes")).json()["total"] == 0

    stored = await db_session.get(Resume, resume.id)
    assert stored is not None
    assert stored.deleted_at is not None


async def test_delete_resume_requires_auth(db_session) -> None:
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.delete(f"/api/v1/resumes/{uuid.uuid4()}")
    assert response.status_code == 401
