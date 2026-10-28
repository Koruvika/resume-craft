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
from resumecraft.core.enums import CompanyStatus
from resumecraft.core.exceptions import CompanyNotReadyError, NotFoundError
from resumecraft.db.models import Company, Task
from resumecraft.db.repositories import company as company_repo
from resumecraft.db.repositories import task as task_repo
from resumecraft.schemas.company import (
    CompanyUpdateRequest,
    ResearchCompanyTaskInput,
)

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
_DEDUP_STATUSES = (CompanyStatus.PENDING, CompanyStatus.PROCESSING, CompanyStatus.COMPLETED)


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


async def create_pending_company(
    session: AsyncSession,
    user_id: UUID,
    company_name: str,
    website: str | None,
) -> Company:
    """Create a PENDING research shell — the research_company task fills in
    reports and flips the status."""
    company = Company(
        user_id=user_id,
        company_name=company_name,
        website=website,
        reports=None,
        status=CompanyStatus.PENDING,
    )
    await company_repo.create(session, company)
    await session.commit()
    return company


async def find_duplicate_company(
    session: AsyncSession,
    user_id: UUID,
    company_name: str,
    website: str | None,
) -> tuple[Company, Task] | None:
    """The user's latest non-failed research from the de-dup window that
    matches this request, with the task that produced it.

    A match needs Jaro-Winkler similarity >= the configured threshold on the
    processed names AND, when both sides have a website, equal processed
    websites. Rows without a task are skipped (there is no handle to return).
    """
    settings = get_settings()
    since = datetime.now(UTC) - timedelta(days=settings.research_dedup_window_days)
    name_key = normalize_company_name(company_name)
    website_key = normalize_website(website)

    candidates = await company_repo.list_recent_for_user(
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
        task = await task_repo.get_latest_for_company(session, candidate.id, user_id)
        if task is not None:
            return candidate, task
    return None


def build_research_task_input(company: Company) -> dict[str, Any]:
    return ResearchCompanyTaskInput(
        company_id=company.id,
        company_name=company.company_name,
        website=company.website,
    ).model_dump(mode="json")


async def get_company_for_user(session: AsyncSession, company_id: UUID, user_id: UUID) -> Company:
    company = await company_repo.get_by_id_for_user(session, company_id, user_id)
    if company is None:
        raise NotFoundError("company", company_id)
    return company


async def list_companies(
    session: AsyncSession,
    user_id: UUID,
    *,
    limit: int,
    offset: int,
    search: str | None = None,
) -> tuple[list[Company], int]:
    return await company_repo.list_for_user(
        session, user_id, limit=limit, offset=offset, search=search
    )


async def run_research(
    session: AsyncSession, task: Task, update_progress: ProgressFn
) -> dict[str, Any]:
    """Work fn for the research_company task: run GPTResearcher against the
    company and complete the research row. Failures are committed onto the
    row before re-raising so the runner still marks the task FAILED."""
    request = ResearchCompanyTaskInput.model_validate(task.input)
    company = await company_repo.get_by_id_for_user(session, request.company_id, task.user_id)
    if company is None:
        raise NotFoundError("company", request.company_id)

    company.status = CompanyStatus.PROCESSING
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
        company.status = CompanyStatus.FAILED
        company.error = str(exc)
        await session.commit()
        raise

    company.reports = reports
    company.status = CompanyStatus.COMPLETED
    company.error = None
    await session.commit()
    await update_progress(1.0)
    return {"company_id": str(company.id)}


async def update_company(
    session: AsyncSession,
    user_id: UUID,
    company_id: UUID,
    request: CompanyUpdateRequest,
) -> Company:
    company = await get_company_for_user(session, company_id, user_id)
    fields = request.model_fields_set
    if "reports" in fields and request.reports is not None:
        if company.status != CompanyStatus.COMPLETED:
            raise CompanyNotReadyError(company.status)
        company.reports = [r.model_dump() for r in request.reports]
    if "company_name" in fields and request.company_name is not None:
        company.company_name = request.company_name
    if "website" in fields:
        company.website = str(request.website) if request.website is not None else None
    await session.commit()
    # updated_at is server-generated (onupdate); reload it for the response.
    await session.refresh(company)
    return company


async def soft_delete_company(session: AsyncSession, user_id: UUID, company_id: UUID) -> None:
    company = await get_company_for_user(session, company_id, user_id)
    company.deleted_at = datetime.now(UTC)
    await session.commit()
