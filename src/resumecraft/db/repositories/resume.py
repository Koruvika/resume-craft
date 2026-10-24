import uuid

from sqlalchemy import select
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
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    return result.scalar_one_or_none()
