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


@pytest.mark.db
async def test_job_type_enum_has_both_values() -> None:
    """The native job_type enum must cover every JobType member (0004)."""
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("select enum_range(null::job_type)"))
            values = set(result.scalar())
            assert values == {"GENERATE_RESUME", "PARSE_RESUME"}
    finally:
        await engine.dispose()
