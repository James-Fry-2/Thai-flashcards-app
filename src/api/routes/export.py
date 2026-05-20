from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import io

from src.api.deps import get_db
from src.db.services import deck_service, card_service
from src.utils.anki_exporter import export_deck_to_apkg, THAI_DECK_BASE_ID

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/decks/{deck_id}/anki")
async def export_anki(deck_id: int, db: AsyncSession = Depends(get_db)):
    deck = await deck_service.get_deck(db, deck_id)
    if not deck:
        raise HTTPException(404, "Deck not found")

    cards = await card_service.get_cards_for_deck(db, deck_id, limit=10000)
    if not cards:
        raise HTTPException(404, "No cards in deck to export")

    apkg_bytes = export_deck_to_apkg(
        deck_name=deck.name,
        deck_id_seed=THAI_DECK_BASE_ID + deck_id,
        cards=cards,
    )

    safe_name = deck.name.replace(" ", "_").replace("/", "-")
    return StreamingResponse(
        io.BytesIO(apkg_bytes),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.apkg"'},
    )
