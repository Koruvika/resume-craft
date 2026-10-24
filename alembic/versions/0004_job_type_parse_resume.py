"""add PARSE_RESUME to job_type enum

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-24

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE works inside a transaction on Postgres >= 12.
    op.execute("alter type job_type add value if not exists 'PARSE_RESUME'")


def downgrade() -> None:
    # Postgres cannot remove a value from an enum type. Restoring the pre-0004
    # code while keeping the database would require recreating the type.
    raise NotImplementedError("job_type values cannot be dropped in Postgres")
