import re
import unicodedata
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from rapidfuzz.distance import JaroWinkler
from sqlalchemy.ext.asyncio import AsyncSession

from resumecraft.core.config import get_settings
from resumecraft.core.enums import ResearchStatus
from resumecraft.core.exceptions import NotFoundError
from resumecraft.db.models import CompanyResearch, Job
from resumecraft.db.repositories import company_research as research_repo
from resumecraft.db.repositories import job as job_repo
from resumecraft.schemas.company_research import CompanyResearchJobInput

ProgressFn = Callable[[float], Awaitable[None]]

# Trailing legal-form tokens dropped before name comparison ("Acme Inc." and
# "ACME Corporation" are the same company). Matched after punctuation removal.
_LEGAL_SUFFIXES = frozenset(
    {
        "inc", "incorporated", "corp", "corporation", "co", "company", "ltd",
        "limited", "llc", "llp", "lp", "plc", "gmbh", "ag", "sa", "sas", "srl",
        "spa", "bv", "nv", "pte", "pty", "oy", "ab", "kk",
    }
)  # fmt: skip
# Statuses a new request can reuse: done, or still running. FAILED never counts.
_DEDUP_STATUSES = (ResearchStatus.PENDING, ResearchStatus.PROCESSING, ResearchStatus.COMPLETED)


def normalize_company_name(name: str) -> str:
    """Comparison key for company names: accent-folded, casefolded,
    punctuation-free, with trailing legal-form suffixes removed."""
    decomposed = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
    text = text.replace("&", " and ").replace(".", "")
    tokens = re.sub(r"[^\w]+", " ", text).split()
    stripped = list(tokens)
    while stripped and stripped[-1] in _LEGAL_SUFFIXES:
        stripped.pop()
    # A name that is nothing but a suffix ("Inc.") keeps its tokens.
    return " ".join(stripped or tokens)


def normalize_website(website: str | None) -> str | None:
    """Comparison key for websites: the lowercased host without a leading
    'www.' — scheme, port, path, query and fragment are ignored."""
    if website is None:
        return None
    host = urlsplit(website if "//" in website else f"//{website}").hostname
    if not host:
        return None
    return host.removeprefix("www.")


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


async def find_duplicate_research(
    session: AsyncSession,
    user_id: UUID,
    company_name: str,
    website: str | None,
) -> tuple[CompanyResearch, Job] | None:
    """The user's latest non-failed research from the de-dup window that
    matches this request, with the job that produced it.

    A match needs Jaro-Winkler similarity >= the configured threshold on the
    processed names AND, when both sides have a website, equal processed
    websites. Rows without a job are skipped (there is no handle to return).
    """
    settings = get_settings()
    since = datetime.now(UTC) - timedelta(days=settings.research_dedup_window_days)
    name_key = normalize_company_name(company_name)
    website_key = normalize_website(website)

    candidates = await research_repo.list_recent_for_user(
        session, user_id, since=since, statuses=_DEDUP_STATUSES
    )
    for candidate in candidates:
        similarity = JaroWinkler.similarity(
            name_key, normalize_company_name(candidate.company_name)
        )
        if similarity < settings.research_dedup_name_threshold:
            continue
        candidate_website_key = normalize_website(candidate.website)
        if website_key and candidate_website_key and website_key != candidate_website_key:
            continue
        job = await job_repo.get_latest_for_research(session, candidate.id, user_id)
        if job is not None:
            return candidate, job
    return None


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
