import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from resumecraft.api.deps import CurrentUserDep, DbSession
from resumecraft.core.celery_app import celery_app
from resumecraft.schemas.company_research import (
    CompanyResearchAcceptedResponse,
    CompanyResearchListOut,
    CompanyResearchOut,
    CompanyResearchRequest,
    CompanyResearchSummaryOut,
)
from resumecraft.services import company_research_service, job_service

router = APIRouter(prefix="/company-research", tags=["company-research"])

COMPANY_RESEARCH_TASK = "resumecraft.worker.tasks.company_research"


@router.post("", response_model=CompanyResearchAcceptedResponse, status_code=202)
async def start_company_research(
    request: CompanyResearchRequest, response: Response, db: DbSession, user: CurrentUserDep
) -> CompanyResearchAcceptedResponse:
    """Start researching a company asynchronously: a PENDING research row is
    created, the company_research job runs GPTResearcher, and
    GET /company-research/{research_id} returns the reports once ready.

    If the user already has a matching research from the last month (pending,
    processing or completed), it is returned with 200 instead — send
    `force: true` to research again anyway."""
    website = str(request.website) if request.website is not None else None
    if not request.force:
        duplicate = await company_research_service.find_duplicate_research(
            db, user.user_id, request.company_name, website
        )
        if duplicate is not None:
            existing, existing_job = duplicate
            response.status_code = 200
            return CompanyResearchAcceptedResponse(
                job_id=existing_job.id, research_id=existing.id, status=existing.status
            )
    research = await company_research_service.create_pending_research(
        db, user.user_id, request.company_name, website
    )
    job_input = company_research_service.build_research_job_input(research)
    job = await job_service.create_company_research_job(db, user.user_id, job_input)
    result = celery_app.send_task(COMPANY_RESEARCH_TASK, kwargs={"job_id": str(job.id)})
    await job_service.attach_task_id(db, job.id, result.id)
    return CompanyResearchAcceptedResponse(
        job_id=job.id, research_id=research.id, status=research.status
    )


@router.get("", response_model=CompanyResearchListOut)
async def list_company_researches(
    db: DbSession,
    user: CurrentUserDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
) -> CompanyResearchListOut:
    """Browse the current user's past company researches (newest first),
    paginated, with an optional case-insensitive company-name search.
    Soft-deleted rows never appear."""
    items, total = await company_research_service.list_researches(
        db, user.user_id, limit=limit, offset=offset, search=search
    )
    return CompanyResearchListOut(
        items=[CompanyResearchSummaryOut.model_validate(r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{research_id}", response_model=CompanyResearchOut)
async def get_company_research(
    research_id: uuid.UUID, db: DbSession, user: CurrentUserDep
) -> CompanyResearchOut:
    """Return one company research with its current status — poll this after
    POST /company-research to know when the reports are ready."""
    research = await company_research_service.get_research_for_user(db, research_id, user.user_id)
    return CompanyResearchOut.model_validate(research)
