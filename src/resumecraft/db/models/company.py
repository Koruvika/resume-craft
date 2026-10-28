import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from resumecraft.core.enums import CompanyStatus
from resumecraft.db.base import Base, JSONVariant, TimestampMixin


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    # One row per research run — re-researching the same company creates a new
    # row, so this is an activity table, not a canonical company entity.
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Null until status is COMPLETED: [{slug, query, report}] per GPTResearcher
    # query, in QUERY_SLUGS order.
    reports: Mapped[list | None] = mapped_column(JSONVariant, nullable=True)
    status: Mapped[CompanyStatus] = mapped_column(
        SAEnum(CompanyStatus, name="company_status"),
        nullable=False,
        default=CompanyStatus.PENDING,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
