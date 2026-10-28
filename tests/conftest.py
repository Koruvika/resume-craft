import uuid
from types import SimpleNamespace

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from resumecraft.api.deps import get_current_user
from resumecraft.core.config import get_settings
from resumecraft.db import models  # noqa: F401  (registers all models)
from resumecraft.db.base import Base
from resumecraft.db.session import get_session
from resumecraft.main import create_app
from resumecraft.schemas.auth import CurrentUser

TEST_USER_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def db_session() -> AsyncSession:
    """In-memory sqlite session with the full schema created (aiosqlite)."""
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def client(db_session, monkeypatch) -> httpx.AsyncClient:
    """Authed API client backed by the in-memory sqlite session, broker stubbed."""
    app = create_app()

    async def _session_override() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id=TEST_USER_ID)

    def fake_send_task(name, args=None, kwargs=None, **_):
        assert name.startswith("resumecraft.worker.tasks.")
        assert kwargs is not None and "task_id" in kwargs
        return SimpleNamespace(id="fake-task-id")

    monkeypatch.setattr("resumecraft.api.v1.resumes.celery_app.send_task", fake_send_task)
    monkeypatch.setattr("resumecraft.api.v1.companies.celery_app.send_task", fake_send_task)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def plain_client(db_session) -> httpx.AsyncClient:
    """API client with DB overridden but real auth — endpoints enforce tokens."""
    app = create_app()

    async def _session_override() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
