from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.api.deps import get_db
from src.db.services.gamification_service import get_profile_with_achievements
from src.db.models.gamification import Achievement

router = APIRouter(prefix="/gamification", tags=["gamification"])


@router.get("/profile")
async def get_profile(db: AsyncSession = Depends(get_db)):
    return await get_profile_with_achievements(db)


@router.get("/achievements")
async def list_achievements(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Achievement))
    achievements = result.scalars().all()
    return [
        {
            "key": a.key,
            "name": a.name,
            "description": a.description,
            "xp_reward": a.xp_reward,
            "icon": a.icon,
        }
        for a in achievements
    ]
