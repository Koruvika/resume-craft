import uuid

from sqlalchemy import Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from resumecraft.db.base import Base, JSONVariant, TimestampMixin


class Resume(Base, TimestampMixin):
    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[dict] = mapped_column(JSONVariant, nullable=False)
