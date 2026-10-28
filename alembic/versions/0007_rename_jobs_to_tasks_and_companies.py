"""rename jobs -> tasks and company_researches -> companies

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-28 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (old, new) pairs — pure renames, no data copy.
_TABLES = (("jobs", "tasks"), ("company_researches", "companies"))
_TYPES = (
    ("job_type", "task_type"),
    ("job_status", "task_status"),
    ("research_status", "company_status"),
)


def _rename_key(table: str, column: str, old: str, new: str) -> None:
    op.execute(
        f"update {table} set {column} = ({column} - '{old}') "  # noqa: S608
        f"|| jsonb_build_object('{new}', {column} -> '{old}') "
        f"where {column} ? '{old}'"
    )


def _rename(
    tables: Sequence[tuple[str, str]],
    types: Sequence[tuple[str, str]],
    value: tuple[str, str],
    key: tuple[str, str],
) -> None:
    for old, new in tables:
        op.rename_table(old, new)
        op.execute(f"alter index ix_{old}_user_id rename to ix_{new}_user_id")
        op.execute(f"alter table {new} rename constraint pk_{old} to pk_{new}")
    for old, new in types:
        op.execute(f"alter type {old} rename to {new}")
    task_table, task_type = tables[0][1], types[0][1]
    op.execute(f"alter type {task_type} rename value '{value[0]}' to '{value[1]}'")
    # research_company task payloads point at the company row by id.
    _rename_key(task_table, "input", *key)
    _rename_key(task_table, "result", *key)


def upgrade() -> None:
    _rename(
        _TABLES,
        _TYPES,
        value=("COMPANY_RESEARCH", "RESEARCH_COMPANY"),
        key=("research_id", "company_id"),
    )


def downgrade() -> None:
    _rename(
        tuple((new, old) for old, new in _TABLES),
        tuple((new, old) for old, new in _TYPES),
        value=("RESEARCH_COMPANY", "COMPANY_RESEARCH"),
        key=("company_id", "research_id"),
    )
