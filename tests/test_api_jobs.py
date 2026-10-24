import uuid

import httpx
from httpx import ASGITransport

from conftest import TEST_USER_ID
from resumecraft.db.session import get_session
from resumecraft.main import create_app
from resumecraft.services import job_service


async def test_get_job(client, db_session) -> None:
    job = await job_service.create_generate_job(db_session, TEST_USER_ID, {"a": 1})
    response = await client.get(f"/api/v1/jobs/{job.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(job.id)
    assert body["status"] == "pending"
    assert body["progress"] == 0.0


async def test_get_job_of_other_user_is_404(client, db_session) -> None:
    job = await job_service.create_generate_job(db_session, uuid.uuid4(), {"a": 1})
    response = await client.get(f"/api/v1/jobs/{job.id}")
    assert response.status_code == 404


async def test_get_job_requires_auth(db_session) -> None:
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get(f"/api/v1/jobs/{uuid.uuid4()}")
    assert response.status_code == 401
