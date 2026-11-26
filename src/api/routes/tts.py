"""Thai audio: card fields, reading-text lines, and ad hoc words.

All audio endpoints return MP3 and are cached on disk (see
src/db/services/tts_service.py). With no TTS provider configured they return
503 {"detail": "tts_not_configured"} so the frontend can fall back to the
browser's own speech synthesis.
"""
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.config.settings import get_settings
from src.db.models.card import Card
from src.db.models.generated_text import GeneratedText
from src.db.services import tts_service
from src.tts import is_configured
from src.utils.current_user import current_user

router = APIRouter(tags=["tts"])

Speed = Literal["normal", "slow"]
_CACHE_HEADERS = {"Cache-Control": "private, max-age=31536000, immutable"}


async def _respond(db: AsyncSession, coro) -> FileResponse:
    try:
        result = await coro
    except tts_service.InvalidTTSText as exc:
        raise HTTPException(422, str(exc))
    except tts_service.TTSNotConfigured:
        raise HTTPException(503, "tts_not_configured")
    except tts_service.TTSError as exc:
        logger.warning(f"TTS failed: {exc}")
        raise HTTPException(502, "tts_failed")
    await db.commit()  # usage row / card_media row
    headers = {**_CACHE_HEADERS, "X-TTS-Cache": "hit" if result.cache_hit else "miss"}
    return FileResponse(result.path, media_type="audio/mpeg", headers=headers)


@router.get("/tts/status")
async def tts_status(db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    return {
        "configured": is_configured(settings),
        "provider": settings.tts_provider,
        "voices": {"female": settings.tts_voice_female, "male": settings.tts_voice_male},
        "usage": await tts_service.usage_summary(db),
    }


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    voice: Literal["female", "male"] = "female"
    speed: Speed = "normal"


@router.post("/tts")
async def speak(payload: SpeakRequest, db: AsyncSession = Depends(get_db)):
    """Any Thai word or phrase (e.g. a word selected in the reader). Thai goes
    in the body rather than the URL."""
    return await _respond(db, tts_service.get_audio(db, payload.text, payload.voice, payload.speed))


@router.get("/cards/{card_id}/audio")
async def card_audio(
    card_id: int,
    field: Literal["thai", "example"] = Query("thai"),
    speed: Speed = Query("normal"),
    db: AsyncSession = Depends(get_db),
):
    card = await db.get(Card, card_id)
    if card is None:
        raise HTTPException(404, "Card not found")
    return await _respond(db, tts_service.card_audio(db, card, field, speed))


@router.get("/reading/texts/{text_id}/lines/{index}/audio")
async def reading_line_audio(
    text_id: int,
    index: int,
    speed: Speed = Query("normal"),
    db: AsyncSession = Depends(get_db),
):
    text = await db.get(GeneratedText, text_id)
    if text is None or text.user_id != current_user():
        raise HTTPException(404, "Text not found")
    lines = json.loads(text.lines)
    if not 0 <= index < len(lines):
        raise HTTPException(404, "Line not found")
    line = lines[index]
    voice = "female"
    if line.get("speaker"):
        voice = tts_service.dialogue_voices(lines).get(line["speaker"], "female")
    return await _respond(db, tts_service.get_audio(db, line.get("thai") or "", voice, speed))
