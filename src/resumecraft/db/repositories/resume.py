import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from resumecraft.db.models import Resume


async def create(session: AsyncSession, resume: Resume) -> Resume:
    session.add(resume)
    await session.flush()
    await session.refresh(resume)
    return resume


async def get_by_id_for_user(
    session: AsyncSession, resume_id: uuid.UUID, user_id: uuid.UUID
) -> Resume | None:
    result = await session.execute(
        select(Resume).where(
            Resume.id == resume_id,
            Resume.user_id == user_id,
            Resume.deleted_at.is_(None),
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
) -> tuple[list[Resume], int]:
    filters = [Resume.user_id == user_id, Resume.deleted_at.is_(None)]
    if search is not None:
        filters.append(Resume.title.ilike(f"%{search}%"))

    total = (
        await session.execute(select(func.count()).select_from(Resume).where(*filters))
    ).scalar_one()
    result = await session.execute(
        select(Resume)
        .where(*filters)
        .order_by(Resume.created_at.desc(), Resume.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total
