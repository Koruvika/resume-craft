from pydantic import BaseModel, Field


class GenerateResumeRequest(BaseModel):
    resume_text: str = Field(min_length=50, description="The candidate's current resume text")
    target_role: str = Field(min_length=2, description="The role to tailor the resume for")


class GeneratedResume(BaseModel):
    """Structured LLM output for resume generation."""

    title: str
    summary: str
    highlights: list[str]
    skills: list[str]
