from fastapi import APIRouter

from resumecraft.api.v1 import health, jobs, resumes

router = APIRouter()
router.include_router(health.router)
router.include_router(jobs.router)
router.include_router(resumes.router)
