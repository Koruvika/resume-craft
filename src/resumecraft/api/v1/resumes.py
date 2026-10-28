import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Response, UploadFile

from resumecraft.api.deps import CurrentUserDep, DbSession
from resumecraft.api.responses import (
    INVALID_INPUT,
    UNAUTHENTICATED,
    error,
    not_found,
)
from resumecraft.core.celery_app import celery_app
from resumecraft.rendering import DEFAULT_LOCALE, DEFAULT_THEME
from resumecraft.schemas.resume import (
    ResumeListOut,
    ResumeOut,
    ResumeSummaryOut,
    ResumeUpdateRequest,
    UploadAcceptedResponse,
    UploadResumeRequest,
)
from resumecraft.services import render_service, resume_service, task_service

router = APIRouter(prefix="/resumes", tags=["resumes"])

RESUME_NOT_READY = error(
    "The resume's parse task has not COMPLETED yet (`resume_not_ready`)",
    "resume_not_ready",
    "Resume is not ready yet",
    {"status": "processing"},
)

PARSE_RESUME_TASK = "resumecraft.worker.tasks.parse_resume"


@router.get(
    "",
    response_model=ResumeListOut,
    responses={401: UNAUTHENTICATED, 422: INVALID_INPUT},
)
async def list_resumes(
    db: DbSession,
    user: CurrentUserDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
) -> ResumeListOut:
    """Browse the current user's resumes (newest first), paginated, with an
    optional case-insensitive title search. Soft-deleted rows never appear."""
    items, total = await resume_service.list_resumes(
        db, user.user_id, limit=limit, offset=offset, search=search
    )
    return ResumeListOut(
        items=[ResumeSummaryOut.model_validate(r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/upload",
    response_model=ResumeOut,
    status_code=201,
    responses={401: UNAUTHENTICATED, 422: INVALID_INPUT},
)
async def upload_resume(
    request: UploadResumeRequest, db: DbSession, user: CurrentUserDep
) -> ResumeOut:
    """Import an already-structured resume (ParsedResume JSON): validated and
    stored synchronously — no LLM, no background task."""
    resume = await resume_service.import_parsed(
        db, user.user_id, request.resume_json, title=request.title
    )
    return ResumeOut.model_validate(resume)


@router.post(
    "/upload-file",
    response_model=UploadAcceptedResponse,
    status_code=202,
    responses={
        401: UNAUTHENTICATED,
        413: error(
            "The file exceeds the size limit for its type (`file_too_large`)",
            "file_too_large",
            "File exceeds 5242880 bytes limit",
            {"size_bytes": 6000000, "max_bytes": 5242880},
        ),
        422: error(
            "Form fields failed validation (`invalid_input`), or the file is not "
            "JSON/PDF (`unsupported_file_type`)",
            "unsupported_file_type",
            "File must be one of application/json, application/pdf",
            {"mime": "text/plain", "supported": ["application/json", "application/pdf"]},
        ),
    },
)
async def upload_resume_file(
    file: Annotated[UploadFile, File(description="A resume as a ParsedResume JSON or PDF file")],
    db: DbSession,
    user: CurrentUserDep,
    title: Annotated[str | None, Form(min_length=1, max_length=255)] = None,
) -> UploadAcceptedResponse:
    """Accept a JSON or PDF resume file asynchronously: a PENDING resume is
    created, the parse_resume task parses it (LlamaCloud for PDFs), and
    GET /resumes/{resume_id} tracks the status."""
    raw = await file.read(resume_service.MAX_PDF_UPLOAD_BYTES + 1)
    source_type = resume_service.classify_upload(file.content_type)
    resume = await resume_service.create_pending_import(
        db, user.user_id, source_type=source_type, raw=raw, filename=file.filename, title=title
    )
    task_input = resume_service.build_parse_task_input(
        resume, source_type=source_type, raw=raw, filename=file.filename, title=title
    )
    task = await task_service.create_parse_task(db, user.user_id, task_input)
    result = celery_app.send_task(PARSE_RESUME_TASK, kwargs={"task_id": str(task.id)})
    await task_service.attach_celery_task_id(db, task.id, result.id)
    return UploadAcceptedResponse(task_id=task.id, resume_id=resume.id, status=resume.status)


@router.get(
    "/{resume_id}",
    response_model=ResumeOut,
    responses={401: UNAUTHENTICATED, 404: not_found("resume"), 422: INVALID_INPUT},
)
async def get_resume(resume_id: uuid.UUID, db: DbSession, user: CurrentUserDep) -> ResumeOut:
    """Return a resume with its current status — poll this after an
    asynchronous upload to know when the content is ready."""
    resume = await resume_service.get_resume_for_user(db, resume_id, user.user_id)
    return ResumeOut.model_validate(resume)


@router.patch(
    "/{resume_id}",
    response_model=ResumeOut,
    responses={
        401: UNAUTHENTICATED,
        404: not_found("resume"),
        409: RESUME_NOT_READY,
        422: INVALID_INPUT,
    },
)
async def update_resume(
    resume_id: uuid.UUID, request: ResumeUpdateRequest, db: DbSession, user: CurrentUserDep
) -> ResumeOut:
    """Partially update a resume (title and/or content). Content may only be
    replaced once the resume is COMPLETED."""
    resume = await resume_service.update_resume(db, user.user_id, resume_id, request)
    return ResumeOut.model_validate(resume)


@router.delete(
    "/{resume_id}",
    status_code=204,
    responses={401: UNAUTHENTICATED, 404: not_found("resume"), 422: INVALID_INPUT},
)
async def delete_resume(resume_id: uuid.UUID, db: DbSession, user: CurrentUserDep) -> None:
    """Soft-delete: sets deleted_at; the row disappears from all reads."""
    await resume_service.soft_delete_resume(db, user.user_id, resume_id)


@router.get(
    "/{resume_id}/pdf",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {}}, "description": "The rendered PDF, inline"},
        401: UNAUTHENTICATED,
        404: not_found("resume"),
        409: RESUME_NOT_READY,
        422: error(
            "Invalid resume id (`invalid_input`), or an unknown theme/locale "
            "(`invalid_render_option`)",
            "invalid_render_option",
            "Unknown theme 'fancy'",
            {"option": "theme", "value": "fancy", "supported": ["classic", "..."]},
        ),
        500: error(
            "The rendercv/typst pipeline failed (`pdf_render_failed`)",
            "pdf_render_failed",
            "Failed to render resume PDF",
        ),
    },
)
async def render_resume_pdf(
    resume_id: uuid.UUID,
    db: DbSession,
    user: CurrentUserDep,
    theme: Annotated[str, Query(description="rendercv theme name")] = DEFAULT_THEME,
    locale: Annotated[str, Query(description="rendercv locale name")] = DEFAULT_LOCALE,
) -> Response:
    """Render a stored resume to PDF — synchronous, no task, no LLM."""
    pdf_bytes, filename = await render_service.render_resume_pdf(
        db, user.user_id, resume_id, theme=theme, locale=locale
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
