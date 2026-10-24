import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from resumecraft.core.config import get_settings


@pytest.mark.db
async def test_migrations_applied() -> None:
    """Requires `docker compose up` + `make migrate` against the dev postgres."""
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            for table_name in ("jobs", "resumes"):
                result = await conn.execute(text(f"select count(*) from {table_name}"))  # noqa: S608
                assert result.scalar() == 0
    finally:
        await engine.dispose()
