"""resume status error and nullable content

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-25 10:52:36.435946

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    resume_status = postgresql.ENUM(
        "PENDING", "PROCESSING", "COMPLETED", "FAILED", name="resume_status"
    )
    resume_status.create(op.get_bind(), checkfirst=True)
    # Existing rows are fully parsed resumes — backfill COMPLETED, then rely on
    # the ORM default (no server default kept).
    op.add_column(
        "resumes",
        sa.Column("status", resume_status, nullable=False, server_default="COMPLETED"),
    )
    op.alter_column("resumes", "status", server_default=None)
    op.add_column("resumes", sa.Column("error", sa.Text(), nullable=True))
    op.alter_column(
        "resumes", "content", existing_type=postgresql.JSONB(astext_type=sa.Text()), nullable=True
    )


def downgrade() -> None:
    op.alter_column(
        "resumes", "content", existing_type=postgresql.JSONB(astext_type=sa.Text()), nullable=False
    )
    op.drop_column("resumes", "error")
    op.drop_column("resumes", "status")
    postgresql.ENUM(name="resume_status", create_type=False).drop(op.get_bind(), checkfirst=True)
