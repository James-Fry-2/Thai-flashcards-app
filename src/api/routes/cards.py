from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, not_, exists
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.db.services import card_service
from src.db.services.card_service import count_cards_for_deck
from src.db.models.card import Card
from src.db.models.tag import CardTag

router = APIRouter(tags=["cards"])


class CardCreate(BaseModel):
    thai: str
    english: str
    romanization: Optional[str] = None
    example_thai: Optional[str] = None
    example_english: Optional[str] = None
    card_type: str = "vocab"


class CardUpdate(BaseModel):
    thai: Optional[str] = None
    english: Optional[str] = None
    romanization: Optional[str] = None
    example_thai: Optional[str] = None
    example_english: Optional[str] = None
    notes: Optional[str] = None
    card_type: Optional[str] = None


def _card_dict(card):
    return {
        "id": card.id,
        "deck_id": card.deck_id,
        "thai": card.thai,
        "romanization": card.romanization,
        "english": card.english,
        "example_thai": card.example_thai,
        "example_english": card.example_english,
        "notes": card.notes,
        "card_type": card.card_type,
        "created_at": card.created_at.isoformat(),
    }


@router.get("/decks/{deck_id}/cards")
async def list_cards(
    deck_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    tagged: Optional[bool] = Query(None, description="true=tagged only, false=untagged only"),
    db: AsyncSession = Depends(get_db),
):
    if tagged is False:
        stmt = (
            select(Card)
            .where(Card.deck_id == deck_id)
            .where(not_(exists(select(CardTag.card_id).where(CardTag.card_id == Card.id))))
            .order_by(Card.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(stmt)
        items = [_card_dict(c) for c in result.scalars().all()]
    else:
        cards = await card_service.get_cards_for_deck(db, deck_id, offset=offset, limit=limit)
        items = [_card_dict(c) for c in cards]

    total = await count_cards_for_deck(db, deck_id)
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.post("/decks/{deck_id}/cards", status_code=201)
async def create_card(deck_id: int, payload: CardCreate, db: AsyncSession = Depends(get_db)):
    card = await card_service.create_card(db, deck_id=deck_id, **payload.model_dump())
    await db.commit()
    return _card_dict(card)


@router.patch("/cards/{card_id}")
async def update_card(card_id: int, payload: CardUpdate, db: AsyncSession = Depends(get_db)):
    card = await card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    card = await card_service.update_card(db, card, **payload.model_dump(exclude_none=True))
    await db.commit()
    return _card_dict(card)


@router.delete("/cards/{card_id}", status_code=204)
async def delete_card(card_id: int, db: AsyncSession = Depends(get_db)):
    card = await card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    await card_service.delete_card(db, card)
    await db.commit()
