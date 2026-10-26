from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from resumecraft.core.enums import ResearchStatus
from resumecraft.core.exceptions import NotFoundError
from resumecraft.db.models import CompanyResearch, Job
from resumecraft.db.repositories import company_research as research_repo
from resumecraft.schemas.company_research import CompanyResearchJobInput

ProgressFn = Callable[[float], Awaitable[None]]


async def create_pending_research(
    session: AsyncSession,
    user_id: UUID,
    company_name: str,
    website: str | None,
) -> CompanyResearch:
    """Create a PENDING research shell — the company_research job fills in
    reports and flips the status."""
    research = CompanyResearch(
        user_id=user_id,
        company_name=company_name,
        website=website,
        reports=None,
        status=ResearchStatus.PENDING,
    )
    await research_repo.create(session, research)
    await session.commit()
    return research


def build_research_job_input(research: CompanyResearch) -> dict[str, Any]:
    return CompanyResearchJobInput(
        research_id=research.id,
        company_name=research.company_name,
        website=research.website,
    ).model_dump(mode="json")


async def get_research_for_user(
    session: AsyncSession, research_id: UUID, user_id: UUID
) -> CompanyResearch:
    research = await research_repo.get_by_id_for_user(session, research_id, user_id)
    if research is None:
        raise NotFoundError("company_research", research_id)
    return research


async def list_researches(
    session: AsyncSession,
    user_id: UUID,
    *,
    limit: int,
    offset: int,
    search: str | None = None,
) -> tuple[list[CompanyResearch], int]:
    return await research_repo.list_for_user(
        session, user_id, limit=limit, offset=offset, search=search
    )


async def run_research(
    session: AsyncSession, job: Job, update_progress: ProgressFn
) -> dict[str, Any]:
    """Work fn for the company_research task: run GPTResearcher against the
    company and complete the research row. Failures are committed onto the
    row before re-raising so the runner still marks the job FAILED."""
    request = CompanyResearchJobInput.model_validate(job.input)
    research = await research_repo.get_by_id_for_user(session, request.research_id, job.user_id)
    if research is None:
        raise NotFoundError("company_research", request.research_id)

    research.status = ResearchStatus.PROCESSING
    await session.commit()
    await update_progress(0.1)

    try:
        from resumecraft.ai import researcher

        reports = await researcher.run_company_research(
            company_name=request.company_name,
            company_urls=[request.website] if request.website else [],
            on_query_done=lambda done: update_progress(
                0.1 + 0.8 * done / len(researcher.QUERY_SLUGS)
            ),
        )
    except Exception as exc:
        research.status = ResearchStatus.FAILED
        research.error = str(exc)
        await session.commit()
        raise

    research.reports = reports
    research.status = ResearchStatus.COMPLETED
    research.error = None
    await session.commit()
    await update_progress(1.0)
    return {"research_id": str(research.id)}


async def soft_delete_research(session: AsyncSession, user_id: UUID, research_id: UUID) -> None:
    research = await get_research_for_user(session, research_id, user_id)
    research.deleted_at = datetime.now(UTC)
    await session.commit()
