import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from resumecraft.core.enums import ResearchStatus


class CompanyResearchRequest(BaseModel):
    """Request body for POST /company-research: research a company through
    its name and (optionally) its website. The website, when given, seeds the
    GPTResearcher source URLs (homepage + common subpages).

    A matching research of the user's from the last month is returned instead
    of starting a new one, unless `force` is set."""

    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(min_length=1, max_length=255)
    website: HttpUrl | None = None
    force: bool = False


class CompanyResearchJobInput(BaseModel):
    """Job.input payload for the company_research task."""

    model_config = ConfigDict(extra="forbid")

    research_id: uuid.UUID
    company_name: str = Field(min_length=1, max_length=255)
    website: str | None = Field(default=None, min_length=1, max_length=2000)


class CompanyResearchAcceptedResponse(BaseModel):
    """Accepted (or de-duplicated) research: poll GET /jobs/{job_id} for the
    job status or GET /company-research/{research_id} for the reports."""

    job_id: uuid.UUID
    research_id: uuid.UUID
    status: ResearchStatus


class ResearchReportOut(BaseModel):
    """One GPTResearcher query result. A failed query keeps its slug and
    query but carries a report of 'ERROR: <cause>'."""

    slug: str
    query: str
    report: str


class CompanyResearchUpdateRequest(BaseModel):
    """Partial update: at least one field must be provided. Omitted fields are
    left alone; `website: null` clears the website.

    Renaming does not re-run the research. Reports may only be replaced on a
    COMPLETED research (409 research_not_ready otherwise) so a client can't
    race an in-flight company_research job.
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


class CompanyResearchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_name: str
    website: str | None = None
    # Null until status is COMPLETED.
    reports: list[ResearchReportOut] | None = None
    status: ResearchStatus
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class CompanyResearchSummaryOut(BaseModel):
    """List row: everything needed to browse past researches without the
    heavy reports."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_name: str
    website: str | None = None
    status: ResearchStatus
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class CompanyResearchListOut(BaseModel):
    items: list[CompanyResearchSummaryOut]
    total: int
    limit: int
    offset: int
