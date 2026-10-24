import httpx
import pytest
from httpx import ASGITransport

from resumecraft.core.config import Settings
from resumecraft.main import create_app


@pytest.fixture
async def client() -> httpx.AsyncClient:
    app = create_app(Settings(_env_file=None))
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_openapi_docs_available_in_dev(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/docs")
    assert response.status_code == 200


async def test_docs_disabled_in_prod() -> None:
    app = create_app(Settings(_env_file=None, app_env="prod"))
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        assert (await c.get("/api/v1/docs")).status_code == 404
