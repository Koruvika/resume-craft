import uuid

from fastapi import APIRouter

from resumecraft.api.deps import CurrentUserDep, DbSession
from resumecraft.api.responses import INVALID_INPUT, UNAUTHENTICATED, not_found
from resumecraft.schemas.job import JobResponse
from resumecraft.services import job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    responses={401: UNAUTHENTICATED, 404: not_found("job"), 422: INVALID_INPUT},
)
async def get_job(job_id: uuid.UUID, db: DbSession, user: CurrentUserDep) -> JobResponse:
    job = await job_service.get_job_for_user(db, job_id, user.user_id)
    return JobResponse.model_validate(job)
