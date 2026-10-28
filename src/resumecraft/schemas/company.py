import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from resumecraft.core.enums import CompanyStatus


class CompanyCreateRequest(BaseModel):
    """Request body for POST /companies: research a company through
    its name and (optionally) its website. The website, when given, seeds the
    GPTResearcher source URLs (homepage + common subpages).

    A matching research of the user's from the last month is returned instead
    of starting a new one, unless `force` is set."""

    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(min_length=1, max_length=255)
    website: HttpUrl | None = None
    force: bool = False


class ResearchCompanyTaskInput(BaseModel):
    """Task.input payload for the research_company task."""

    model_config = ConfigDict(extra="forbid")

    company_id: uuid.UUID
    company_name: str = Field(min_length=1, max_length=255)
    website: str | None = Field(default=None, min_length=1, max_length=2000)


class CompanyAcceptedResponse(BaseModel):
    """Accepted (or de-duplicated) research: poll GET /tasks/{task_id} for the
    task status or GET /companies/{company_id} for the reports."""

    task_id: uuid.UUID
    company_id: uuid.UUID
    status: CompanyStatus


class ResearchReportOut(BaseModel):
    """One GPTResearcher query result. A failed query keeps its slug and
    query but carries a report of 'ERROR: <cause>'."""

    slug: str
    query: str
    report: str


class CompanyUpdateRequest(BaseModel):
    """Partial update: at least one field must be provided. Omitted fields are
    left alone; `website: null` clears the website.

    Renaming does not re-run the research. Reports may only be replaced on a
    COMPLETED research (409 company_not_ready otherwise) so a client can't
    race an in-flight research_company task.
    """

    model_config = ConfigDict(extra="forbid")

    company_name: str | None = Field(default=None, min_length=1, max_length=255)
    website: HttpUrl | None = None
    reports: list[ResearchReportOut] | None = None

    @model_validator(mode="after")
    def _check_fields(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Provide at least one of: company_name, website, reports")
        if "company_name" in self.model_fields_set and self.company_name is None:
            raise ValueError("company_name cannot be null")
        if "reports" in self.model_fields_set and self.reports is None:
            raise ValueError("reports cannot be null")
        return self


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_name: str
    website: str | None = None
    # Null until status is COMPLETED.
    reports: list[ResearchReportOut] | None = None
    status: CompanyStatus
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class CompanySummaryOut(BaseModel):
    """List row: everything needed to browse past companies without the
    heavy reports."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_name: str
    website: str | None = None
    status: CompanyStatus
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class CompanyListOut(BaseModel):
    items: list[CompanySummaryOut]
    total: int
    limit: int
    offset: int
