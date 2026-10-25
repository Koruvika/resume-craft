import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from resumecraft.db.models import CompanyResearch


async def create(session: AsyncSession, research: CompanyResearch) -> CompanyResearch:
    session.add(research)
    await session.flush()
    await session.refresh(research)
    return research


async def get_by_id_for_user(
    session: AsyncSession, research_id: uuid.UUID, user_id: uuid.UUID
) -> CompanyResearch | None:
    result = await session.execute(
        select(CompanyResearch).where(
            CompanyResearch.id == research_id,
            CompanyResearch.user_id == user_id,
            CompanyResearch.deleted_at.is_(None),
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
) -> tuple[list[CompanyResearch], int]:
    filters = [CompanyResearch.user_id == user_id, CompanyResearch.deleted_at.is_(None)]
    if search is not None:
        filters.append(CompanyResearch.company_name.ilike(f"%{search}%"))

    total = (
        await session.execute(select(func.count()).select_from(CompanyResearch).where(*filters))
    ).scalar_one()
    result = await session.execute(
        select(CompanyResearch)
        .where(*filters)
        .order_by(CompanyResearch.created_at.desc(), CompanyResearch.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total
