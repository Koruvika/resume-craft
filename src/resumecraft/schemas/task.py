import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from resumecraft.core.enums import TaskStatus, TaskType


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: TaskType
    status: TaskStatus
    progress: float
    result: dict | None
    error: str | None
    created_at: datetime
