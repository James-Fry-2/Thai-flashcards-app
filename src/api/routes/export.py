from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
import io

from src.api.deps import get_db
from src.db.services import deck_service, card_service, tts_service
from src.utils.anki_exporter import export_deck_to_apkg, THAI_DECK_BASE_ID

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/decks/{deck_id}/anki/audio")
async def anki_audio_estimate(deck_id: int, db: AsyncSession = Depends(get_db)):
    """How much of the deck's audio exists, and what generating the rest costs."""
    from src.tts import is_configured

    cards = await card_service.get_cards_for_deck(db, deck_id, limit=10000)
    batch = await tts_service.ensure_card_audio(db, cards, generate=False)
    return {
        "configured": is_configured(),
        "cards": len(cards),
        "cached": batch.cached,
        "missing": batch.missing,
        "missing_chars": batch.to_generate_chars,
    }


@router.get("/decks/{deck_id}/anki")
async def export_anki(
    deck_id: int,
    audio: Literal["none", "cached", "all"] = Query(
        "cached",
        description="none: no audio. cached: include clips already generated (free, instant). "
        "all: generate any missing clips first (uses TTS characters).",
    ),
    db: AsyncSession = Depends(get_db),
):
    deck = await deck_service.get_deck(db, deck_id)
    if not deck:
        raise HTTPException(404, "Deck not found")

    cards = await card_service.get_cards_for_deck(db, deck_id, limit=10000)
    if not cards:
        raise HTTPException(404, "No cards in deck to export")

    clips = {}
    if audio != "none":
        try:
            batch = await tts_service.ensure_card_audio(db, cards, generate=audio == "all")
        except tts_service.TTSNotConfigured:
            batch = await tts_service.ensure_card_audio(db, cards, generate=False)
        await db.commit()
        clips = {(card_id, field): path for (card_id, field, _speed), path in batch.paths.items()}
        logger.info(
            f"Anki export deck {deck_id}: {len(clips)} clips "
            f"(generated {batch.generated}, failed {batch.failed}, missing {batch.missing})"
        )

    apkg_bytes = export_deck_to_apkg(
        deck_name=deck.name,
        deck_id_seed=THAI_DECK_BASE_ID + deck_id,
        cards=cards,
        audio=clips,
    )

    safe_name = deck.name.replace(" ", "_").replace("/", "-")
    return StreamingResponse(
        io.BytesIO(apkg_bytes),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.apkg"'},
    )
