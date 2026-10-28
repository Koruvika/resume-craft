import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from resumecraft.core.enums import ResumeStatus
from resumecraft.db.base import Base, JSONVariant, TimestampMixin


class Resume(Base, TimestampMixin):
    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # Null while an upload/parse task is still running; set once parsed.
    content: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    status: Mapped[ResumeStatus] = mapped_column(
        SAEnum(ResumeStatus, name="resume_status"),
        nullable=False,
        default=ResumeStatus.COMPLETED,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
