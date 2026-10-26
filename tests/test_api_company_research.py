import uuid
from datetime import UTC, datetime

import httpx
from httpx import ASGITransport
from sqlalchemy import select

from conftest import TEST_USER_ID
from resumecraft.core.enums import ResearchStatus
from resumecraft.db.models import CompanyResearch
from resumecraft.db.repositories import job as job_repo
from resumecraft.db.session import get_session
from resumecraft.main import create_app
from resumecraft.services import company_research_service

REQUEST_BODY = {"company_name": "Acme", "website": "https://acme.com"}


async def test_start_research_returns_202_with_handles(client, db_session) -> None:
    response = await client.post("/api/v1/company-research", json=REQUEST_BODY)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    research_id = uuid.UUID(body["research_id"])

    research = (await db_session.execute(select(CompanyResearch))).scalars().one()
    assert research.id == research_id
    assert research.company_name == "Acme"
    # HttpUrl normalizes to a trailing slash.
    assert research.website == "https://acme.com/"
    assert research.status == ResearchStatus.PENDING
    assert research.reports is None

    job = await job_repo.get_by_id(db_session, uuid.UUID(body["job_id"]))
    assert job is not None
    assert job.type == "company_research"
    assert job.celery_task_id == "fake-task-id"
    assert job.input["research_id"] == str(research.id)
    assert job.input["company_name"] == "Acme"
    assert job.input["website"] == "https://acme.com/"


async def test_start_research_without_website(client, db_session) -> None:
    response = await client.post("/api/v1/company-research", json={"company_name": "Acme"})
    assert response.status_code == 202

    research = (await db_session.execute(select(CompanyResearch))).scalars().one()
    assert research.website is None


async def test_start_research_rejects_blank_name(client) -> None:
    response = await client.post(
        "/api/v1/company-research", json={"company_name": "", "website": "https://acme.com"}
    )
    assert response.status_code == 422


async def test_start_research_rejects_bad_website(client) -> None:
    response = await client.post(
        "/api/v1/company-research", json={"company_name": "Acme", "website": "not-a-url"}
    )
    assert response.status_code == 422


async def test_start_research_rejects_extra_fields(client) -> None:
    response = await client.post("/api/v1/company-research", json={**REQUEST_BODY, "reports": []})
    assert response.status_code == 422


async def test_start_research_twice_returns_existing_research(client, db_session) -> None:
    first = await client.post("/api/v1/company-research", json=REQUEST_BODY)
    assert first.status_code == 202

    second = await client.post(
        "/api/v1/company-research",
        json={"company_name": "ACME Inc.", "website": "https://www.acme.com"},
    )

    assert second.status_code == 200
    assert second.json() == first.json()
    researches = (await db_session.execute(select(CompanyResearch))).scalars().all()
    assert len(researches) == 1


async def test_start_research_with_force_skips_dedup(client, db_session) -> None:
    first = await client.post("/api/v1/company-research", json=REQUEST_BODY)

    second = await client.post("/api/v1/company-research", json={**REQUEST_BODY, "force": True})

    assert second.status_code == 202
    assert second.json()["research_id"] != first.json()["research_id"]
    researches = (await db_session.execute(select(CompanyResearch))).scalars().all()
    assert len(researches) == 2


async def test_start_research_different_website_is_not_a_duplicate(client) -> None:
    first = await client.post("/api/v1/company-research", json=REQUEST_BODY)

    second = await client.post(
        "/api/v1/company-research", json={"company_name": "Acme", "website": "https://acme.io"}
    )

    assert second.status_code == 202
    assert second.json()["research_id"] != first.json()["research_id"]


async def test_start_research_requires_auth(db_session) -> None:
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.post("/api/v1/company-research", json=REQUEST_BODY)
    assert response.status_code == 401


async def _seed(
    db_session,
    user_id,
    *,
    company_name: str,
    created_at,
    completed: bool = False,
) -> CompanyResearch:
    research = CompanyResearch(
        user_id=user_id,
        company_name=company_name,
        reports=(
            [{"slug": "customers", "query": "Who?", "report": "Buyers."}] if completed else None
        ),
        status=ResearchStatus.COMPLETED if completed else ResearchStatus.PENDING,
        created_at=created_at,
    )
    db_session.add(research)
    await db_session.commit()
    return research


async def test_get_research_returns_pending_status(client, db_session) -> None:
    research = await _seed(
        db_session,
        TEST_USER_ID,
        company_name="Acme",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    response = await client.get(f"/api/v1/company-research/{research.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(research.id)
    assert body["company_name"] == "Acme"
    assert body["status"] == "pending"
    assert body["reports"] is None


async def test_get_research_returns_completed_reports(client, db_session) -> None:
    research = await _seed(
        db_session,
        TEST_USER_ID,
        company_name="Acme",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        completed=True,
    )

    response = await client.get(f"/api/v1/company-research/{research.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["reports"] == [{"slug": "customers", "query": "Who?", "report": "Buyers."}]


async def test_get_research_unknown_returns_404(client) -> None:
    response = await client.get(f"/api/v1/company-research/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "company_research_not_found"


async def test_get_research_other_user_is_404(client, db_session) -> None:
    research = await _seed(
        db_session,
        uuid.uuid4(),
        company_name="Not mine",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    response = await client.get(f"/api/v1/company-research/{research.id}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "company_research_not_found"


async def test_get_research_requires_auth(db_session) -> None:
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get(f"/api/v1/company-research/{uuid.uuid4()}")
    assert response.status_code == 401


async def test_list_researches_returns_newest_first_envelope(client, db_session) -> None:
    older = await _seed(
        db_session,
        TEST_USER_ID,
        company_name="Older",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    newer = await _seed(
        db_session,
        TEST_USER_ID,
        company_name="Newer",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    response = await client.get("/api/v1/company-research")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert [item["id"] for item in body["items"]] == [str(newer.id), str(older.id)]
    assert set(body["items"][0]) == {
        "id",
        "company_name",
        "website",
        "status",
        "error",
        "created_at",
        "updated_at",
    }


async def test_list_researches_pagination_and_search(client, db_session) -> None:
    await _seed(
        db_session,
        TEST_USER_ID,
        company_name="Acme",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    await _seed(
        db_session,
        TEST_USER_ID,
        company_name="Globex",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    response = await client.get("/api/v1/company-research", params={"limit": 1, "offset": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["company_name"] for item in body["items"]] == ["Acme"]

    response = await client.get("/api/v1/company-research", params={"search": "GLOBEX"})
    body = response.json()
    assert body["total"] == 1
    assert [item["company_name"] for item in body["items"]] == ["Globex"]


async def test_list_researches_excludes_other_users_and_deleted(client, db_session) -> None:
    await _seed(
        db_session,
        uuid.uuid4(),
        company_name="Not mine",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    mine = await _seed(
        db_session,
        TEST_USER_ID,
        company_name="Mine",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    await company_research_service.soft_delete_research(db_session, TEST_USER_ID, mine.id)

    response = await client.get("/api/v1/company-research")

    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_list_researches_requires_auth(db_session) -> None:
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get("/api/v1/company-research")
    assert response.status_code == 401


async def test_update_research_renames_and_changes_website(client, db_session) -> None:
    research = await _seed(
        db_session, TEST_USER_ID, company_name="Acme", created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    response = await client.patch(
        f"/api/v1/company-research/{research.id}",
        json={"company_name": "Acme Corp", "website": "https://acme.io"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["company_name"] == "Acme Corp"
    assert body["website"] == "https://acme.io/"
    assert body["status"] == "pending"


async def test_update_research_null_website_clears_it(client, db_session) -> None:
    research = await _seed(
        db_session, TEST_USER_ID, company_name="Acme", created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    await client.patch(
        f"/api/v1/company-research/{research.id}", json={"website": "https://acme.io"}
    )

    response = await client.patch(f"/api/v1/company-research/{research.id}", json={"website": None})

    assert response.status_code == 200
    assert response.json()["website"] is None
    assert response.json()["company_name"] == "Acme"


async def test_update_research_replaces_reports_when_completed(client, db_session) -> None:
    research = await _seed(
        db_session,
        TEST_USER_ID,
        company_name="Acme",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        completed=True,
    )
    reports = [{"slug": "customers", "query": "Who?", "report": "Edited."}]

    response = await client.patch(
        f"/api/v1/company-research/{research.id}", json={"reports": reports}
    )

    assert response.status_code == 200
    assert response.json()["reports"] == reports


async def test_update_research_reports_before_completed_is_409(client, db_session) -> None:
    research = await _seed(
        db_session, TEST_USER_ID, company_name="Acme", created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    response = await client.patch(
        f"/api/v1/company-research/{research.id}",
        json={"reports": [{"slug": "customers", "query": "Who?", "report": "Early."}]},
    )

    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "research_not_ready"
    assert body["details"] == {"status": "pending"}


async def test_update_research_rejects_empty_and_invalid_bodies(client, db_session) -> None:
    research = await _seed(
        db_session, TEST_USER_ID, company_name="Acme", created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    url = f"/api/v1/company-research/{research.id}"

    for body in (
        {},
        {"company_name": ""},
        {"company_name": None},
        {"website": "not-a-url"},
        {"reports": None},
        {"status": "completed"},
    ):
        response = await client.patch(url, json=body)
        assert response.status_code == 422, body


async def test_update_research_other_user_is_404(client, db_session) -> None:
    research = await _seed(
        db_session,
        uuid.uuid4(),
        company_name="Not mine",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    response = await client.patch(
        f"/api/v1/company-research/{research.id}", json={"company_name": "Mine now"}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "company_research_not_found"


async def test_delete_research_soft_deletes(client, db_session) -> None:
    research = await _seed(
        db_session, TEST_USER_ID, company_name="Acme", created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    response = await client.delete(f"/api/v1/company-research/{research.id}")

    assert response.status_code == 204
    assert response.content == b""
    assert (await client.get(f"/api/v1/company-research/{research.id}")).status_code == 404
    assert (await client.delete(f"/api/v1/company-research/{research.id}")).status_code == 404
    await db_session.refresh(research)
    assert research.deleted_at is not None


async def test_delete_research_other_user_is_404(client, db_session) -> None:
    research = await _seed(
        db_session,
        uuid.uuid4(),
        company_name="Not mine",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    response = await client.delete(f"/api/v1/company-research/{research.id}")

    assert response.status_code == 404
    await db_session.refresh(research)
    assert research.deleted_at is None
