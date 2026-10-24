import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from resumecraft.core.enums import JobStatus, JobType


class JobAcceptedResponse(BaseModel):
    job_id: uuid.UUID
    status: JobStatus


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: JobType
    status: JobStatus
    progress: float
    result: dict | None
    error: str | None
    created_at: datetime
