from fastapi import APIRouter
from sqlalchemy import text

from resumecraft.api.deps import DbSession
from resumecraft.api.responses import INTERNAL_ERROR

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/db", responses={500: INTERNAL_ERROR})
async def health_db(db: DbSession) -> dict[str, str]:
    await db.execute(text("select 1"))
    return {"status": "ok"}
