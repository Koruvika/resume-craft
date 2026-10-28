import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from resumecraft.core.enums import ResumeStatus
from resumecraft.schemas.parsed_resume import ParsedResume


class UploadResumeRequest(BaseModel):
    """Import an already-structured resume: validated as ParsedResume and stored
    synchronously (no LLM, no task). Raw file uploads (JSON/PDF) go through
    POST /resumes/upload-file and the parse_resume task instead.
    """

    resume_json: ParsedResume
    # Falls back to the resume's headline / full name when omitted.
    title: str | None = Field(default=None, min_length=1, max_length=255)


class ParseUploadTaskInput(BaseModel):
    """Task.input payload for the parse_resume task."""

    model_config = {"extra": "forbid"}

    resume_id: uuid.UUID
    source_type: Literal["json", "pdf"]
    file_b64: str
    filename: str
    title: str | None = Field(default=None, min_length=1, max_length=255)


class UploadAcceptedResponse(BaseModel):
    """Accepted upload: poll GET /resumes/{resume_id} for the resume status."""

    task_id: uuid.UUID
    resume_id: uuid.UUID
    status: ResumeStatus


class ResumeOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    # Null until status is COMPLETED.
    content: ParsedResume | None = None
    status: ResumeStatus
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class ResumeSummaryOut(BaseModel):
    """List row: everything needed to browse/paginate without the heavy content."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    title: str
    status: ResumeStatus
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class ResumeListOut(BaseModel):
    items: list[ResumeSummaryOut]
    total: int
    limit: int
    offset: int


class ResumeUpdateRequest(BaseModel):
    """Partial update: at least one of title/content must be provided.

    Content may only be replaced on a COMPLETED resume (409 resume_not_ready
    otherwise) so a client can't race an in-flight parse task.
    """

    model_config = {"extra": "forbid"}

    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: ParsedResume | None = None

    @model_validator(mode="after")
    def _require_one_field(self) -> Self:
        if self.title is None and self.content is None:
            raise ValueError("Provide at least one of: title, content")
        return self
