import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from resumecraft.core.enums import JobStatus, JobType
from resumecraft.db.base import Base, JSONVariant, TimestampMixin


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    type: Mapped[JobType] = mapped_column(SAEnum(JobType, name="job_type"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, name="job_status"), nullable=False, default=JobStatus.PENDING
    )
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    input: Mapped[dict] = mapped_column(JSONVariant, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
