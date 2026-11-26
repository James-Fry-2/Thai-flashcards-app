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
        "daily_new_limit": prefs.daily_new_limit,
        "daily_review_limit": prefs.daily_review_limit,
        "tts_autoplay_on_reveal": prefs.tts_autoplay_on_reveal,
        "tts_default_speed": prefs.tts_default_speed,
        "card_font": prefs.card_font,
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
    daily_new_limit: Optional[int] = None
    daily_review_limit: Optional[int] = None
    tts_autoplay_on_reveal: Optional[bool] = None
    tts_default_speed: Optional[str] = None
    card_font: Optional[str] = None


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
            daily_new_limit=payload.daily_new_limit,
            daily_review_limit=payload.daily_review_limit,
            tts_autoplay_on_reveal=payload.tts_autoplay_on_reveal,
            tts_default_speed=payload.tts_default_speed,
            card_font=payload.card_font,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    await db.commit()
    return _prefs_dict(prefs)
