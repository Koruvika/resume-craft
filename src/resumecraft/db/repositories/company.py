import uuid
from collections.abc import Collection
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from resumecraft.core.enums import CompanyStatus
from resumecraft.db.models import Company


async def create(session: AsyncSession, company: Company) -> Company:
    session.add(company)
    await session.flush()
    await session.refresh(company)
    return company


async def get_by_id_for_user(
    session: AsyncSession, company_id: uuid.UUID, user_id: uuid.UUID
) -> Company | None:
    result = await session.execute(
        select(Company).where(
            Company.id == company_id,
            Company.user_id == user_id,
            Company.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def list_for_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
    search: str | None = None,
) -> tuple[list[Company], int]:
    filters = [Company.user_id == user_id, Company.deleted_at.is_(None)]
    if search is not None:
        filters.append(Company.company_name.ilike(f"%{search}%"))

    total = (
        await session.execute(select(func.count()).select_from(Company).where(*filters))
    ).scalar_one()
    result = await session.execute(
        select(Company)
        .where(*filters)
        .order_by(Company.created_at.desc(), Company.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def list_recent_for_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    since: datetime,
    statuses: Collection[CompanyStatus],
) -> list[Company]:
    """Live companies created at/after `since` in the given statuses,
    newest first."""
    result = await session.execute(
        select(Company)
        .where(
            Company.user_id == user_id,
            Company.deleted_at.is_(None),
            Company.created_at >= since,
            Company.status.in_(statuses),
        )
        .order_by(Company.created_at.desc(), Company.id.desc())
    )
    return list(result.scalars().all())
