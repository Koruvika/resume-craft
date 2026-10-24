from fastapi import APIRouter

from resumecraft.api.v1 import health

router = APIRouter()
router.include_router(health.router)
