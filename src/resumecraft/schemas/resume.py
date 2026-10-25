import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from resumecraft.core.enums import ResumeStatus
from resumecraft.schemas.parsed_resume import ParsedResume


class UploadResumeRequest(BaseModel):
    """Import an already-structured resume: validated as ParsedResume and stored
    synchronously (no LLM, no job). Raw file uploads (JSON/PDF) go through
    POST /resumes/upload-file and the parse_resume job instead.
    """

    resume_json: ParsedResume
    # Falls back to the resume's headline / full name when omitted.
    title: str | None = Field(default=None, min_length=1, max_length=255)


class ParseUploadJobInput(BaseModel):
    """Job.input payload for the parse_resume task."""

    model_config = {"extra": "forbid"}

    resume_id: uuid.UUID
    source_type: Literal["json", "pdf"]
    file_b64: str
    filename: str
    title: str | None = Field(default=None, min_length=1, max_length=255)


class UploadAcceptedResponse(BaseModel):
    """Accepted upload: poll GET /resumes/{resume_id} for the resume status."""

    job_id: uuid.UUID
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
