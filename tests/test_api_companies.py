import uuid
from datetime import UTC, datetime

import httpx
from httpx import ASGITransport
from sqlalchemy import select

from conftest import TEST_USER_ID
from resumecraft.core.enums import CompanyStatus
from resumecraft.db.models import Company
from resumecraft.db.repositories import task as task_repo
from resumecraft.db.session import get_session
from resumecraft.main import create_app
from resumecraft.services import company_service

REQUEST_BODY = {"company_name": "Acme", "website": "https://acme.com"}


async def test_create_company_returns_202_with_handles(client, db_session) -> None:
    response = await client.post("/api/v1/companies", json=REQUEST_BODY)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    company_id = uuid.UUID(body["company_id"])

    company = (await db_session.execute(select(Company))).scalars().one()
    assert company.id == company_id
    assert company.company_name == "Acme"
    # HttpUrl normalizes to a trailing slash.
    assert company.website == "https://acme.com/"
    assert company.status == CompanyStatus.PENDING
    assert company.reports is None

    task = await task_repo.get_by_id(db_session, uuid.UUID(body["task_id"]))
    assert task is not None
    assert task.type == "research_company"
    assert task.celery_task_id == "fake-task-id"
    assert task.input["company_id"] == str(company.id)
    assert task.input["company_name"] == "Acme"
    assert task.input["website"] == "https://acme.com/"


async def test_create_company_without_website(client, db_session) -> None:
    response = await client.post("/api/v1/companies", json={"company_name": "Acme"})
    assert response.status_code == 202

    company = (await db_session.execute(select(Company))).scalars().one()
    assert company.website is None


async def test_create_company_rejects_blank_name(client) -> None:
    response = await client.post(
        "/api/v1/companies", json={"company_name": "", "website": "https://acme.com"}
    )
    assert response.status_code == 422


async def test_create_company_rejects_bad_website(client) -> None:
    response = await client.post(
        "/api/v1/companies", json={"company_name": "Acme", "website": "not-a-url"}
    )
    assert response.status_code == 422


async def test_create_company_rejects_extra_fields(client) -> None:
    response = await client.post("/api/v1/companies", json={**REQUEST_BODY, "reports": []})
    assert response.status_code == 422


async def test_create_company_twice_returns_existing_company(client, db_session) -> None:
    first = await client.post("/api/v1/companies", json=REQUEST_BODY)
    assert first.status_code == 202

    second = await client.post(
        "/api/v1/companies",
        json={"company_name": "ACME Inc.", "website": "https://www.acme.com"},
    )

    assert second.status_code == 200
    assert second.json() == first.json()
    companies = (await db_session.execute(select(Company))).scalars().all()
    assert len(companies) == 1


async def test_create_company_with_force_skips_dedup(client, db_session) -> None:
    first = await client.post("/api/v1/companies", json=REQUEST_BODY)

    second = await client.post("/api/v1/companies", json={**REQUEST_BODY, "force": True})

    assert second.status_code == 202
    assert second.json()["company_id"] != first.json()["company_id"]
    companies = (await db_session.execute(select(Company))).scalars().all()
    assert len(companies) == 2


async def test_create_company_different_website_is_not_a_duplicate(client) -> None:
    first = await client.post("/api/v1/companies", json=REQUEST_BODY)

    second = await client.post(
        "/api/v1/companies", json={"company_name": "Acme", "website": "https://acme.io"}
    )

    assert second.status_code == 202
    assert second.json()["company_id"] != first.json()["company_id"]


async def test_create_company_requires_auth(db_session) -> None:
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.post("/api/v1/companies", json=REQUEST_BODY)
    assert response.status_code == 401


async def _seed(
    db_session,
    user_id,
    *,
    company_name: str,
    created_at,
    completed: bool = False,
) -> Company:
    company = Company(
        user_id=user_id,
        company_name=company_name,
        reports=(
            [{"slug": "customers", "query": "Who?", "report": "Buyers."}] if completed else None
        ),
        status=CompanyStatus.COMPLETED if completed else CompanyStatus.PENDING,
        created_at=created_at,
    )
    db_session.add(company)
    await db_session.commit()
    return company


async def test_get_company_returns_pending_status(client, db_session) -> None:
    company = await _seed(
        db_session,
        TEST_USER_ID,
        company_name="Acme",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    response = await client.get(f"/api/v1/companies/{company.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(company.id)
    assert body["company_name"] == "Acme"
    assert body["status"] == "pending"
    assert body["reports"] is None


async def test_get_company_returns_completed_reports(client, db_session) -> None:
    company = await _seed(
        db_session,
        TEST_USER_ID,
        company_name="Acme",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        completed=True,
    )

    response = await client.get(f"/api/v1/companies/{company.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["reports"] == [{"slug": "customers", "query": "Who?", "report": "Buyers."}]


async def test_get_company_unknown_returns_404(client) -> None:
    response = await client.get(f"/api/v1/companies/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "company_not_found"


async def test_get_company_other_user_is_404(client, db_session) -> None:
    company = await _seed(
        db_session,
        uuid.uuid4(),
        company_name="Not mine",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    response = await client.get(f"/api/v1/companies/{company.id}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "company_not_found"


async def test_get_company_requires_auth(db_session) -> None:
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get(f"/api/v1/companies/{uuid.uuid4()}")
    assert response.status_code == 401


async def test_list_companies_returns_newest_first_envelope(client, db_session) -> None:
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

    response = await client.get("/api/v1/companies")

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


async def test_list_companies_pagination_and_search(client, db_session) -> None:
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

    response = await client.get("/api/v1/companies", params={"limit": 1, "offset": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["company_name"] for item in body["items"]] == ["Acme"]

    response = await client.get("/api/v1/companies", params={"search": "GLOBEX"})
    body = response.json()
    assert body["total"] == 1
    assert [item["company_name"] for item in body["items"]] == ["Globex"]


async def test_list_companies_excludes_other_users_and_deleted(client, db_session) -> None:
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
    await company_service.soft_delete_company(db_session, TEST_USER_ID, mine.id)

    response = await client.get("/api/v1/companies")

    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_list_companies_requires_auth(db_session) -> None:
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get("/api/v1/companies")
    assert response.status_code == 401


async def test_update_company_renames_and_changes_website(client, db_session) -> None:
    company = await _seed(
        db_session, TEST_USER_ID, company_name="Acme", created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    response = await client.patch(
        f"/api/v1/companies/{company.id}",
        json={"company_name": "Acme Corp", "website": "https://acme.io"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["company_name"] == "Acme Corp"
    assert body["website"] == "https://acme.io/"
    assert body["status"] == "pending"


async def test_update_company_null_website_clears_it(client, db_session) -> None:
    company = await _seed(
        db_session, TEST_USER_ID, company_name="Acme", created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    await client.patch(f"/api/v1/companies/{company.id}", json={"website": "https://acme.io"})

    response = await client.patch(f"/api/v1/companies/{company.id}", json={"website": None})

    assert response.status_code == 200
    assert response.json()["website"] is None
    assert response.json()["company_name"] == "Acme"


async def test_update_company_replaces_reports_when_completed(client, db_session) -> None:
    company = await _seed(
        db_session,
        TEST_USER_ID,
        company_name="Acme",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        completed=True,
    )
    reports = [{"slug": "customers", "query": "Who?", "report": "Edited."}]

    response = await client.patch(f"/api/v1/companies/{company.id}", json={"reports": reports})

    assert response.status_code == 200
    assert response.json()["reports"] == reports


async def test_update_company_reports_before_completed_is_409(client, db_session) -> None:
    company = await _seed(
        db_session, TEST_USER_ID, company_name="Acme", created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    response = await client.patch(
        f"/api/v1/companies/{company.id}",
        json={"reports": [{"slug": "customers", "query": "Who?", "report": "Early."}]},
    )

    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "company_not_ready"
    assert body["details"] == {"status": "pending"}


async def test_update_company_rejects_empty_and_invalid_bodies(client, db_session) -> None:
    company = await _seed(
        db_session, TEST_USER_ID, company_name="Acme", created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    url = f"/api/v1/companies/{company.id}"

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


async def test_update_company_other_user_is_404(client, db_session) -> None:
    company = await _seed(
        db_session,
        uuid.uuid4(),
        company_name="Not mine",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    response = await client.patch(
        f"/api/v1/companies/{company.id}", json={"company_name": "Mine now"}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "company_not_found"


async def test_delete_company_soft_deletes(client, db_session) -> None:
    company = await _seed(
        db_session, TEST_USER_ID, company_name="Acme", created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    response = await client.delete(f"/api/v1/companies/{company.id}")

    assert response.status_code == 204
    assert response.content == b""
    assert (await client.get(f"/api/v1/companies/{company.id}")).status_code == 404
    assert (await client.delete(f"/api/v1/companies/{company.id}")).status_code == 404
    await db_session.refresh(company)
    assert company.deleted_at is not None


async def test_delete_company_other_user_is_404(client, db_session) -> None:
    company = await _seed(
        db_session,
        uuid.uuid4(),
        company_name="Not mine",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    response = await client.delete(f"/api/v1/companies/{company.id}")

    assert response.status_code == 404
    await db_session.refresh(company)
    assert company.deleted_at is None
