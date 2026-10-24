from collections.abc import Awaitable, Callable
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from resumecraft.ai.llm.client import get_chat_model
from resumecraft.db.models import Job, Resume
from resumecraft.db.repositories import resume as resume_repo
from resumecraft.prompts.resume import GENERATE_RESUME_PROMPT, PARSE_RESUME_PROMPT
from resumecraft.schemas.parsed_resume import ParsedResume
from resumecraft.schemas.resume import GenerateResumeRequest, ParseResumeRequest

ProgressFn = Callable[[float], Awaitable[None]]


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


async def parse(
    session: AsyncSession,
    job: Job,
    update_progress: ProgressFn,
    request: ParseResumeRequest,
) -> ParsedResume:
    parsed = await _run_structured(
        PARSE_RESUME_PROMPT.format(resume_text=request.resume_text),
        update_progress,
        (0.2, 0.7),
    )
    title = _title_for(parsed, "Imported resume")
    await resume_repo.create(
        session,
        Resume(user_id=job.user_id, title=title, content=parsed.model_dump()),
    )
    await session.commit()
    await update_progress(1.0)
    return parsed


async def import_parsed(session: AsyncSession, user_id: UUID, parsed: ParsedResume) -> Resume:
    resume = Resume(
        user_id=user_id,
        title=_title_for(parsed, "Imported resume"),
        content=parsed.model_dump(),
    )
    await resume_repo.create(session, resume)
    await session.commit()
    return resume
