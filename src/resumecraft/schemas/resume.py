import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field, model_validator

from resumecraft.schemas.parsed_resume import ParsedResume


class GenerateResumeRequest(BaseModel):
    resume_text: str = Field(min_length=50, description="The candidate's current resume text")
    target_role: str = Field(min_length=2, description="The role to tailor the resume for")


class ParseResumeRequest(BaseModel):
    resume_text: str = Field(min_length=50, description="The candidate's current resume text")


class UploadResumeRequest(BaseModel):
    """Import a resume: exactly one of structured JSON or raw text.

    - `resume_json`: a ParsedResume (already structured) — stored immediately.
    - `resume_text`: raw text — parsed into a ParsedResume by the parse_resume job.
    - PDF binary upload will be a separate multipart endpoint later.
    """

    resume_json: ParsedResume | None = None
    resume_text: str | None = Field(default=None, min_length=50)

    @model_validator(mode="after")
    def exactly_one_source(self) -> Self:
        if (self.resume_json is None) == (self.resume_text is None):
            raise ValueError("Provide exactly one of resume_json or resume_text")
        return self


class ResumeOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    content: ParsedResume
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
