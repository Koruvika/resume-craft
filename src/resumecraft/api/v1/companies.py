import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from resumecraft.api.deps import CurrentUserDep, DbSession
from resumecraft.api.responses import INVALID_INPUT, UNAUTHENTICATED, error, not_found
from resumecraft.core.celery_app import celery_app
from resumecraft.schemas.company import (
    CompanyAcceptedResponse,
    CompanyCreateRequest,
    CompanyListOut,
    CompanyOut,
    CompanySummaryOut,
    CompanyUpdateRequest,
)
from resumecraft.services import company_service, task_service

router = APIRouter(prefix="/companies", tags=["companies"])

RESEARCH_COMPANY_TASK = "resumecraft.worker.tasks.research_company"


@router.post(
    "",
    response_model=CompanyAcceptedResponse,
    status_code=202,
    responses={
        200: {
            "model": CompanyAcceptedResponse,
            "description": "A matching research from the last month already exists "
            "(and `force` is false); its task and company ids are returned",
        },
        401: UNAUTHENTICATED,
        422: INVALID_INPUT,
    },
)
async def create_company(
    request: CompanyCreateRequest, response: Response, db: DbSession, user: CurrentUserDep
) -> CompanyAcceptedResponse:
    """Start researching a company asynchronously: a PENDING research row is
    created, the research_company task runs GPTResearcher, and
    GET /companies/{company_id} returns the reports once ready.

    If the user already has a matching research from the last month (pending,
    processing or completed), it is returned with 200 instead — send
    `force: true` to research again anyway."""
    website = str(request.website) if request.website is not None else None
    if not request.force:
        duplicate = await company_service.find_duplicate_company(
            db, user.user_id, request.company_name, website
        )
        if duplicate is not None:
            existing, existing_task = duplicate
            response.status_code = 200
            return CompanyAcceptedResponse(
                task_id=existing_task.id, company_id=existing.id, status=existing.status
            )
    company = await company_service.create_pending_company(
        db, user.user_id, request.company_name, website
    )
    task_input = company_service.build_research_task_input(company)
    task = await task_service.create_research_task(db, user.user_id, task_input)
    result = celery_app.send_task(RESEARCH_COMPANY_TASK, kwargs={"task_id": str(task.id)})
    await task_service.attach_celery_task_id(db, task.id, result.id)
    return CompanyAcceptedResponse(task_id=task.id, company_id=company.id, status=company.status)


@router.get(
    "",
    response_model=CompanyListOut,
    responses={401: UNAUTHENTICATED, 422: INVALID_INPUT},
)
async def list_companies(
    db: DbSession,
    user: CurrentUserDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
) -> CompanyListOut:
    """Browse the current user's past company researches (newest first),
    paginated, with an optional case-insensitive company-name search.
    Soft-deleted rows never appear."""
    items, total = await company_service.list_companies(
        db, user.user_id, limit=limit, offset=offset, search=search
    )
    return CompanyListOut(
        items=[CompanySummaryOut.model_validate(r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{company_id}",
    response_model=CompanyOut,
    responses={401: UNAUTHENTICATED, 404: not_found("company"), 422: INVALID_INPUT},
)
async def get_company(company_id: uuid.UUID, db: DbSession, user: CurrentUserDep) -> CompanyOut:
    """Return one company research with its current status — poll this after
    POST /companies to know when the reports are ready."""
    company = await company_service.get_company_for_user(db, company_id, user.user_id)
    return CompanyOut.model_validate(company)


@router.patch(
    "/{company_id}",
    response_model=CompanyOut,
    responses={
        401: UNAUTHENTICATED,
        404: not_found("company"),
        409: error(
            "Reports sent before the research is COMPLETED (`company_not_ready`)",
            "company_not_ready",
            "Company research is not ready yet",
            {"status": "processing"},
        ),
        422: INVALID_INPUT,
    },
)
async def update_company(
    company_id: uuid.UUID,
    request: CompanyUpdateRequest,
    db: DbSession,
    user: CurrentUserDep,
) -> CompanyOut:
    """Partially update a research (company name, website and/or reports).
    Renaming does not re-run the research; reports may only be replaced once
    the research is COMPLETED."""
    company = await company_service.update_company(db, user.user_id, company_id, request)
    return CompanyOut.model_validate(company)


@router.delete(
    "/{company_id}",
    status_code=204,
    responses={401: UNAUTHENTICATED, 404: not_found("company"), 422: INVALID_INPUT},
)
async def delete_company(company_id: uuid.UUID, db: DbSession, user: CurrentUserDep) -> None:
    """Soft-delete: sets deleted_at; the row disappears from all reads and
    from de-duplication."""
    await company_service.soft_delete_company(db, user.user_id, company_id)
