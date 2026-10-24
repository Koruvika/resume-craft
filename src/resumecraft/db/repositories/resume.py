from sqlalchemy.ext.asyncio import AsyncSession

from resumecraft.db.models import Resume


async def create(session: AsyncSession, resume: Resume) -> Resume:
    session.add(resume)
    await session.flush()
    await session.refresh(resume)
    return resume
