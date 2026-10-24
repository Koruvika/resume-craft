from fastapi import APIRouter

from resumecraft.api.v1 import auth, health, jobs, resumes

router = APIRouter()
router.include_router(auth.router)
router.include_router(health.router)
router.include_router(jobs.router)
router.include_router(resumes.router)
