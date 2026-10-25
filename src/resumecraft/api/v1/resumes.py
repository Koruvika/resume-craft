import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Response, UploadFile

from resumecraft.api.deps import CurrentUserDep, DbSession
from resumecraft.core.celery_app import celery_app
from resumecraft.rendering import DEFAULT_LOCALE, DEFAULT_THEME
from resumecraft.schemas.resume import ResumeOut, UploadAcceptedResponse, UploadResumeRequest
from resumecraft.services import job_service, render_service, resume_service

router = APIRouter(prefix="/resumes", tags=["resumes"])

PARSE_RESUME_TASK = "resumecraft.worker.tasks.parse_resume"


@router.post("/upload", response_model=ResumeOut, status_code=201)
async def upload_resume(
    request: UploadResumeRequest, db: DbSession, user: CurrentUserDep
) -> ResumeOut:
    """Import an already-structured resume (ParsedResume JSON): validated and
    stored synchronously — no LLM, no background job."""
    resume = await resume_service.import_parsed(
        db, user.user_id, request.resume_json, title=request.title
    )
    return ResumeOut.model_validate(resume)


@router.post("/upload-file", response_model=UploadAcceptedResponse, status_code=202)
async def upload_resume_file(
    file: Annotated[UploadFile, File(description="A resume as a ParsedResume JSON or PDF file")],
    db: DbSession,
    user: CurrentUserDep,
    title: Annotated[str | None, Form(min_length=1, max_length=255)] = None,
) -> UploadAcceptedResponse:
    """Accept a JSON or PDF resume file asynchronously: a PENDING resume is
    created, the parse_resume job parses it (LlamaCloud for PDFs), and
    GET /resumes/{resume_id} tracks the status."""
    raw = await file.read(resume_service.MAX_PDF_UPLOAD_BYTES + 1)
    source_type = resume_service.classify_upload(file.content_type)
    resume = await resume_service.create_pending_import(
        db, user.user_id, source_type=source_type, raw=raw, filename=file.filename, title=title
    )
    job_input = resume_service.build_parse_job_input(
        resume, source_type=source_type, raw=raw, filename=file.filename, title=title
    )
    job = await job_service.create_parse_job(db, user.user_id, job_input)
    result = celery_app.send_task(PARSE_RESUME_TASK, kwargs={"job_id": str(job.id)})
    await job_service.attach_task_id(db, job.id, result.id)
    return UploadAcceptedResponse(job_id=job.id, resume_id=resume.id, status=resume.status)


@router.get("/{resume_id}", response_model=ResumeOut)
async def get_resume(resume_id: uuid.UUID, db: DbSession, user: CurrentUserDep) -> ResumeOut:
    """Return a resume with its current status — poll this after an
    asynchronous upload to know when the content is ready."""
    resume = await resume_service.get_resume_for_user(db, resume_id, user.user_id)
    return ResumeOut.model_validate(resume)


@router.get("/{resume_id}/pdf")
async def render_resume_pdf(
    resume_id: uuid.UUID,
    db: DbSession,
    user: CurrentUserDep,
    theme: Annotated[str, Query(description="rendercv theme name")] = DEFAULT_THEME,
    locale: Annotated[str, Query(description="rendercv locale name")] = DEFAULT_LOCALE,
) -> Response:
    """Render a stored resume to PDF — synchronous, no job, no LLM."""
    pdf_bytes, filename = await render_service.render_resume_pdf(
        db, user.user_id, resume_id, theme=theme, locale=locale
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
