import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from resumecraft.schemas.parsed_resume import ParsedResume


class GenerateResumeRequest(BaseModel):
    resume_text: str = Field(min_length=50, description="The candidate's current resume text")
    target_role: str = Field(min_length=2, description="The role to tailor the resume for")


class UploadResumeRequest(BaseModel):
    """Import an already-structured resume: validated as ParsedResume and stored
    synchronously (no LLM, no job). Only JSON today; raw-text/PDF upload would
    come later as a separate flow.
    """

    resume_json: ParsedResume


class ResumeOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    content: ParsedResume
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
