from fastapi import APIRouter, Response

from resumecraft.api.deps import CurrentUserDep, DbSession
from resumecraft.core.celery_app import celery_app
from resumecraft.schemas.job import JobAcceptedResponse
from resumecraft.schemas.resume import GenerateResumeRequest, ResumeOut, UploadResumeRequest
from resumecraft.services import job_service, resume_service

router = APIRouter(prefix="/resumes", tags=["resumes"])

GENERATE_RESUME_TASK = "resumecraft.worker.tasks.generate_resume"
PARSE_RESUME_TASK = "resumecraft.worker.tasks.parse_resume"


@router.post("/generate", response_model=JobAcceptedResponse, status_code=202)
async def generate_resume(
    request: GenerateResumeRequest, db: DbSession, user: CurrentUserDep
) -> JobAcceptedResponse:
    job = await job_service.create_generate_job(db, user.user_id, request.model_dump())
    result = celery_app.send_task(GENERATE_RESUME_TASK, kwargs={"job_id": str(job.id)})
    await job_service.attach_task_id(db, job.id, result.id)
    return JobAcceptedResponse(job_id=job.id, status=job.status)


@router.post(
    "/upload",
    response_model=None,
    status_code=201,
    responses={202: {"model": JobAcceptedResponse, "description": "Text accepted for parsing"}},
)
async def upload_resume(
    request: UploadResumeRequest, db: DbSession, user: CurrentUserDep, response: Response
) -> ResumeOut | JobAcceptedResponse:
    """Import a resume: structured JSON is stored immediately (201), raw text is
    parsed by the parse_resume job (202). PDF upload comes later as multipart."""
    if request.resume_json is not None:
        resume = await resume_service.import_parsed(db, user.user_id, request.resume_json)
        return ResumeOut.model_validate(resume)

    job = await job_service.create_parse_job(db, user.user_id, {"resume_text": request.resume_text})
    result = celery_app.send_task(PARSE_RESUME_TASK, kwargs={"job_id": str(job.id)})
    await job_service.attach_task_id(db, job.id, result.id)
    response.status_code = 202
    return JobAcceptedResponse(job_id=job.id, status=job.status)
