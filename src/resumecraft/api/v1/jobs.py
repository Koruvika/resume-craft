import uuid

from fastapi import APIRouter, HTTPException, status

from resumecraft.api.deps import CurrentUserDep, DbSession
from resumecraft.schemas.job import JobResponse
from resumecraft.services import job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: uuid.UUID, db: DbSession, user: CurrentUserDep) -> JobResponse:
    try:
        job = await job_service.get_job_for_user(db, job_id, user.user_id)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found") from None
    return JobResponse.model_validate(job)
