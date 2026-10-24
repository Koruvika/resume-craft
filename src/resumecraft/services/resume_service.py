import json
from collections.abc import Awaitable, Callable
from typing import cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from resumecraft.ai.llm.client import get_chat_model
from resumecraft.db.models import Job, Resume
from resumecraft.db.repositories import resume as resume_repo
from resumecraft.prompts.resume import GENERATE_RESUME_PROMPT
from resumecraft.schemas.parsed_resume import ParsedResume
from resumecraft.schemas.resume import GenerateResumeRequest

ProgressFn = Callable[[float], Awaitable[None]]

# Defensive cap: a ParsedResume is a few KB of text, so 1 MiB is already generous.
MAX_UPLOAD_BYTES = 1024 * 1024


class UnsupportedUploadContentType(ValueError):
    """Upload's declared content type is not application/json."""


class UploadTooLarge(ValueError):
    """Upload exceeds MAX_UPLOAD_BYTES."""


class InvalidUploadJSON(ValueError):
    """Bytes are not valid JSON or do not validate as a ParsedResume.

    `detail` carries the pydantic error list for schema violations.
    """

    def __init__(self, message: str, detail: object | None = None) -> None:
        super().__init__(message)
        self.detail = detail


def _title_for(parsed: ParsedResume, fallback: str) -> str:
    return parsed.contact_info.headline or parsed.contact_info.full_name or fallback


async def _run_structured(
    prompt: str, progress: ProgressFn, at: tuple[float, float]
) -> ParsedResume:
    model = get_chat_model().with_structured_output(ParsedResume)
    await progress(at[0])
    parsed = cast("ParsedResume", await model.ainvoke(prompt))
    await progress(at[1])
    return parsed


async def generate(
    session: AsyncSession,
    job: Job,
    update_progress: ProgressFn,
    request: GenerateResumeRequest,
) -> ParsedResume:
    parsed = await _run_structured(
        GENERATE_RESUME_PROMPT.format(
            resume_text=request.resume_text, target_role=request.target_role
        ),
        update_progress,
        (0.2, 0.7),
    )
    title = _title_for(parsed, f"Resume for {request.target_role}")
    await resume_repo.create(
        session,
        Resume(user_id=job.user_id, title=title, content=parsed.model_dump()),
    )
    await session.commit()
    await update_progress(1.0)
    return parsed


async def import_parsed(
    session: AsyncSession, user_id: UUID, parsed: ParsedResume, title: str | None = None
) -> Resume:
    resume = Resume(
        user_id=user_id,
        title=title or _title_for(parsed, "Imported resume"),
        content=parsed.model_dump(),
    )
    await resume_repo.create(session, resume)
    await session.commit()
    return resume


async def import_file(
    session: AsyncSession,
    user_id: UUID,
    *,
    raw: bytes,
    content_type: str | None,
    title: str | None = None,
) -> Resume:
    """Validate uploaded resume bytes and store them, same as import_parsed."""
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared != "application/json":
        raise UnsupportedUploadContentType("File must be application/json")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise UploadTooLarge(f"File exceeds {MAX_UPLOAD_BYTES} bytes limit")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise InvalidUploadJSON("File is not valid JSON") from None
    try:
        parsed = ParsedResume.model_validate(data)
    except ValidationError as exc:
        raise InvalidUploadJSON(
            "File is not a valid ParsedResume", detail=json.loads(exc.json())
        ) from None
    return await import_parsed(session, user_id, parsed, title=title)
