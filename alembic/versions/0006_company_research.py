"""company research table and job type

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-25 14:51:26.354673

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE works inside a transaction on Postgres >= 12.
    op.execute("alter type job_type add value if not exists 'COMPANY_RESEARCH'")
    op.create_table(
        "company_researches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("company_name", sa.Text(), nullable=False),
        sa.Column("website", sa.Text(), nullable=True),
        sa.Column(
            "reports",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum("PENDING", "PROCESSING", "COMPLETED", "FAILED", name="research_status"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company_researches")),
    )
    op.create_index(
        op.f("ix_company_researches_user_id"), "company_researches", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_company_researches_user_id"), table_name="company_researches")
    op.drop_table("company_researches")
    postgresql.ENUM(name="research_status", create_type=False).drop(op.get_bind(), checkfirst=True)
    # Postgres cannot remove a value from an enum type: 'COMPANY_RESEARCH'
    # stays in job_type after downgrade (same tradeoff as revision 0004).
