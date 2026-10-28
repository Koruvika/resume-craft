from fastapi import APIRouter

from resumecraft.api.v1 import auth, companies, health, resumes, tasks

router = APIRouter()
router.include_router(auth.router)
router.include_router(companies.router)
router.include_router(health.router)
router.include_router(tasks.router)
router.include_router(resumes.router)
