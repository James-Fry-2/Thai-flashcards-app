from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.db.services import deck_service

router = APIRouter(prefix="/decks", tags=["decks"])


class DeckCreate(BaseModel):
    name: str
    description: Optional[str] = None


class DeckUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


@router.get("/")
async def list_decks(db: AsyncSession = Depends(get_db)):
    decks = await deck_service.list_decks(db)
    result = []
    for deck in decks:
        stats = await deck_service.get_deck_stats(db, deck.id)
        result.append({
            "id": deck.id,
            "name": deck.name,
            "description": deck.description,
            "source_lang": deck.source_lang,
            "target_lang": deck.target_lang,
            "created_at": deck.created_at.isoformat(),
            **stats,
        })
    return result


@router.post("/", status_code=201)
async def create_deck(payload: DeckCreate, db: AsyncSession = Depends(get_db)):
    deck = await deck_service.create_deck(db, name=payload.name, description=payload.description)
    await db.commit()
    return {"id": deck.id, "name": deck.name, "description": deck.description}


@router.get("/{deck_id}")
async def get_deck(deck_id: int, db: AsyncSession = Depends(get_db)):
    deck = await deck_service.get_deck(db, deck_id)
    if not deck:
        raise HTTPException(404, "Deck not found")
    stats = await deck_service.get_deck_stats(db, deck_id)
    return {
        "id": deck.id,
        "name": deck.name,
        "description": deck.description,
        "source_lang": deck.source_lang,
        "target_lang": deck.target_lang,
        "created_at": deck.created_at.isoformat(),
        **stats,
    }


@router.patch("/{deck_id}")
async def update_deck(deck_id: int, payload: DeckUpdate, db: AsyncSession = Depends(get_db)):
    deck = await deck_service.get_deck(db, deck_id)
    if not deck:
        raise HTTPException(404, "Deck not found")
    updates = payload.model_dump(exclude_none=True)
    deck = await deck_service.update_deck(db, deck, **updates)
    await db.commit()
    return {"id": deck.id, "name": deck.name, "description": deck.description}


@router.delete("/{deck_id}", status_code=204)
async def delete_deck(deck_id: int, db: AsyncSession = Depends(get_db)):
    deck = await deck_service.get_deck(db, deck_id)
    if not deck:
        raise HTTPException(404, "Deck not found")
    await deck_service.delete_deck(db, deck)
    await db.commit()
