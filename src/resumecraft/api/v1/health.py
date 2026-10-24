from fastapi import APIRouter
from sqlalchemy import text

from resumecraft.api.deps import DbSession

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/db")
async def health_db(db: DbSession) -> dict[str, str]:
    await db.execute(text("select 1"))
    return {"status": "ok"}
