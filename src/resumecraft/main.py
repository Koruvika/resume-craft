from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from sqlalchemy import text

from resumecraft.api.v1.router import router as v1_router
from resumecraft.core.config import Settings, get_settings
from resumecraft.core.logging import configure_logging
from resumecraft.db.session import dispose_engine, init_engine

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    engine = init_engine(settings)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        logger.info("database_connection_ok")
    except Exception:
        logger.warning("database_connection_failed_at_startup")
    yield
    await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="resumecraft",
        docs_url="/api/v1/docs" if settings.app_env != "prod" else None,
        lifespan=lifespan,
    )
    app.include_router(v1_router, prefix="/api/v1")
    return app


app = create_app()
