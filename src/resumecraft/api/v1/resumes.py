from fastapi import APIRouter

from resumecraft.api.deps import CurrentUserDep, DbSession
from resumecraft.core.celery_app import celery_app
from resumecraft.schemas.job import JobAcceptedResponse
from resumecraft.schemas.resume import GenerateResumeRequest
from resumecraft.services import job_service

router = APIRouter(prefix="/resumes", tags=["resumes"])

GENERATE_RESUME_TASK = "resumecraft.worker.tasks.generate_resume"


@router.post("/generate", response_model=JobAcceptedResponse, status_code=202)
async def generate_resume(
    request: GenerateResumeRequest, db: DbSession, user: CurrentUserDep
) -> JobAcceptedResponse:
    job = await job_service.create_generate_job(db, user.user_id, request.model_dump())
    result = celery_app.send_task(GENERATE_RESUME_TASK, kwargs={"job_id": str(job.id)})
    await job_service.attach_task_id(db, job.id, result.id)
    return JobAcceptedResponse(job_id=job.id, status=job.status)
