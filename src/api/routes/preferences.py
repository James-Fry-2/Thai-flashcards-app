from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.db.services import preferences_service

router = APIRouter(prefix="/preferences", tags=["preferences"])


def _prefs_dict(prefs) -> dict:
    return {
        "romanization_display": prefs.romanization_display,
        "romanization_fallback": prefs.romanization_fallback,
        "updated_at": prefs.updated_at.isoformat(),
    }


@router.get("/")
async def get_preferences(db: AsyncSession = Depends(get_db)):
    prefs = await preferences_service.get_preferences(db)
    await db.commit()
    return _prefs_dict(prefs)


class PreferencesUpdate(BaseModel):
    romanization_display: Optional[str] = None
    romanization_fallback: Optional[str] = None


@router.patch("/")
async def update_preferences(
    payload: PreferencesUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        prefs = await preferences_service.update_preferences(
            db,
            romanization_display=payload.romanization_display,
            romanization_fallback=payload.romanization_fallback,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    await db.commit()
    return _prefs_dict(prefs)
