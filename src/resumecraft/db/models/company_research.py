import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from resumecraft.core.enums import ResearchStatus
from resumecraft.db.base import Base, JSONVariant, TimestampMixin


class CompanyResearch(Base, TimestampMixin):
    __tablename__ = "company_researches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    # One row per research run — re-researching the same company creates a new
    # row, so this is an activity table, not a canonical company entity.
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Null until status is COMPLETED: [{slug, query, report}] per GPTResearcher
    # query, in QUERY_SLUGS order.
    reports: Mapped[list | None] = mapped_column(JSONVariant, nullable=True)
    status: Mapped[ResearchStatus] = mapped_column(
        SAEnum(ResearchStatus, name="research_status"),
        nullable=False,
        default=ResearchStatus.PENDING,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
