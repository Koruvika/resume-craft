import uuid

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from resumecraft.core.exceptions import NotFoundError, PdfRenderError
from resumecraft.db.repositories import resume as resume_repo
from resumecraft.rendering import (
    build_rendercv_model,
    generate_pdf_bytes,
    parsed_resume_to_rendercv,
    validate_render_options,
)
from resumecraft.schemas.parsed_resume import ParsedResume


async def render_resume_pdf(
    session: AsyncSession,
    user_id: uuid.UUID,
    resume_id: uuid.UUID,
    *,
    theme: str | None = None,
    locale: str | None = None,
) -> tuple[bytes, str]:
    """Render a stored resume to PDF bytes, synchronously.

    The DB read is async; the rendercv/typst pipeline is CPU work, so it runs
    in a worker thread to keep the event loop free for other requests.
    """
    options = validate_render_options(theme, locale)

    resume = await resume_repo.get_by_id_for_user(session, resume_id, user_id)
    if resume is None:
        raise NotFoundError("resume", resume_id)

    parsed = ParsedResume.model_validate(resume.content)
    model = build_rendercv_model(parsed_resume_to_rendercv(parsed), options)

    filename = f"resume-{resume_id}.pdf"
    try:
        pdf_bytes, filename = await anyio.to_thread.run_sync(generate_pdf_bytes, model, filename)
    except Exception as exc:
        # Inputs are validated before rendering, so a failure past this point
        # is ours (theme bug, font issue) — not something the client can fix.
        raise PdfRenderError("Failed to render resume PDF") from exc
    return pdf_bytes, filename
