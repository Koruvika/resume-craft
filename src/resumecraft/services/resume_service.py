from collections.abc import Awaitable, Callable
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from resumecraft.ai.llm.client import get_chat_model
from resumecraft.db.models import Job, Resume
from resumecraft.db.repositories import resume as resume_repo
from resumecraft.prompts.resume import GENERATE_RESUME_PROMPT
from resumecraft.schemas.resume import GeneratedResume, GenerateResumeRequest

ProgressFn = Callable[[float], Awaitable[None]]


async def generate(
    session: AsyncSession,
    job: Job,
    update_progress: ProgressFn,
    request: GenerateResumeRequest,
) -> GeneratedResume:
    model = get_chat_model().with_structured_output(GeneratedResume)
    await update_progress(0.2)
    generated = cast(
        "GeneratedResume",
        await model.ainvoke(
            GENERATE_RESUME_PROMPT.format(
                resume_text=request.resume_text, target_role=request.target_role
            )
        ),
    )
    await update_progress(0.7)
    await resume_repo.create(
        session,
        Resume(user_id=job.user_id, title=generated.title, content=generated.model_dump()),
    )
    await session.commit()
    await update_progress(1.0)
    return generated
