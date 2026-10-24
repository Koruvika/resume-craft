import uuid

from sqlalchemy import Boolean, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from resumecraft.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # 320 = 64 local part + @ + 255 domain, the RFC 5321 maximum. Unique because it
    # is the login key.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    # A bcrypt hash, never the password. Must never be logged, returned in a
    # response, or compared with `==`. `UserOut` deliberately has no field for it.
    # Self-describing (`$2b$12$...`), so the work factor can be raised without a
    # migration — `needs_rehash` replaces the old hash at the next successful login.
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    # Deactivation rather than deletion: users own jobs/resumes that must not
    # cascade away.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
