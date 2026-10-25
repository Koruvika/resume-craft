import base64
import json
from collections.abc import Awaitable, Callable
from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from resumecraft.ai.parser import parse_pdf
from resumecraft.core.enums import ResumeStatus
from resumecraft.core.exceptions import (
    FileTooLargeError,
    InvalidResumeFileError,
    NotFoundError,
    UnsupportedFileTypeError,
)
from resumecraft.db.models import Job, Resume
from resumecraft.db.repositories import resume as resume_repo
from resumecraft.schemas.parsed_resume import ParsedResume
from resumecraft.schemas.resume import ParseUploadJobInput

ProgressFn = Callable[[float], Awaitable[None]]

# Defensive caps: a ParsedResume is a few KB of text, PDFs are heavier.
MAX_UPLOAD_BYTES = 1024 * 1024
MAX_PDF_UPLOAD_BYTES = 5 * 1024 * 1024

SUPPORTED_UPLOAD_TYPES = ["application/json", "application/pdf"]


def _title_for(parsed: ParsedResume, fallback: str) -> str:
    return parsed.contact_info.headline or parsed.contact_info.full_name or fallback


def _filename_stem(filename: str) -> str:
    return PurePosixPath(filename).stem or "Imported resume"


def classify_upload(content_type: str | None) -> Literal["json", "pdf"]:
    """Map a declared content type to a source_type, rejecting others."""
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared == "application/json":
        return "json"
    if declared == "application/pdf":
        return "pdf"
    raise UnsupportedFileTypeError(
        declared or "unknown",
        SUPPORTED_UPLOAD_TYPES,
        message=f"File must be one of {', '.join(SUPPORTED_UPLOAD_TYPES)}",
    )


def _max_bytes_for(source_type: str) -> int:
    return MAX_PDF_UPLOAD_BYTES if source_type == "pdf" else MAX_UPLOAD_BYTES


def _validate_json_bytes(raw: bytes) -> ParsedResume:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise InvalidResumeFileError("File is not valid JSON") from None
    try:
        return ParsedResume.model_validate(data)
    except ValidationError as exc:
        raise InvalidResumeFileError(
            "File is not a valid ParsedResume",
            details={"fields": json.loads(exc.json())},
        ) from None


async def import_parsed(
    session: AsyncSession, user_id: UUID, parsed: ParsedResume, title: str | None = None
) -> Resume:
    """Create a COMPLETED resume from an already-parsed ParsedResume."""
    resume = Resume(
        user_id=user_id,
        title=title or _title_for(parsed, "Imported resume"),
        content=parsed.model_dump(),
    )
    await resume_repo.create(session, resume)
    await session.commit()
    return resume


async def get_resume_for_user(session: AsyncSession, resume_id: UUID, user_id: UUID) -> Resume:
    resume = await resume_repo.get_by_id_for_user(session, resume_id, user_id)
    if resume is None:
        raise NotFoundError("resume", resume_id)
    return resume


async def create_pending_import(
    session: AsyncSession,
    user_id: UUID,
    *,
    source_type: str,
    raw: bytes,
    filename: str | None,
    title: str | None = None,
) -> Resume:
    """Create a PENDING resume shell for an uploaded file — the parse_resume
    job fills in content and flips the status."""
    max_bytes = _max_bytes_for(source_type)
    if len(raw) > max_bytes:
        raise FileTooLargeError(
            size_bytes=len(raw),
            max_bytes=max_bytes,
            message=f"File exceeds {max_bytes} bytes limit",
        )
    fallback = _filename_stem(filename or f"resume.{source_type}")
    resume = Resume(
        user_id=user_id,
        title=title or fallback,
        content=None,
        status=ResumeStatus.PENDING,
    )
    await resume_repo.create(session, resume)
    await session.commit()
    return resume


def build_parse_job_input(
    resume: Resume,
    *,
    source_type: Literal["json", "pdf"],
    raw: bytes,
    filename: str | None,
    title: str | None,
) -> dict[str, Any]:
    return ParseUploadJobInput(
        resume_id=resume.id,
        source_type=source_type,
        file_b64=base64.b64encode(raw).decode(),
        filename=filename or f"resume.{source_type}",
        title=title,
    ).model_dump(mode="json")


async def parse_upload(
    session: AsyncSession, job: Job, update_progress: ProgressFn
) -> dict[str, Any]:
    """Work fn for the parse_resume task: parse the uploaded file and complete
    the resume. Failures are committed onto the resume before re-raising so
    the runner still marks the job FAILED."""
    request = ParseUploadJobInput.model_validate(job.input)
    resume = await resume_repo.get_by_id_for_user(session, request.resume_id, job.user_id)
    if resume is None:
        raise NotFoundError("resume", request.resume_id)

    resume.status = ResumeStatus.PROCESSING
    await session.commit()
    await update_progress(0.2)

    try:
        file_bytes = base64.b64decode(request.file_b64, validate=False)
        if request.source_type == "pdf":
            parsed = await parse_pdf(file_bytes, request.filename)
        else:
            parsed = _validate_json_bytes(file_bytes)
    except Exception as exc:
        resume.status = ResumeStatus.FAILED
        resume.error = str(exc)
        await session.commit()
        raise

    await update_progress(0.8)
    resume.content = parsed.model_dump()
    resume.status = ResumeStatus.COMPLETED
    resume.error = None
    if request.title is None:
        resume.title = _title_for(parsed, _filename_stem(request.filename))
    await session.commit()
    await update_progress(1.0)
    return {"resume_id": str(resume.id)}
