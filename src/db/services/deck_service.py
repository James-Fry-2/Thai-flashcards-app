from typing import List, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.deck import Deck
from src.db.models.card import Card
from src.db.models.card_schedule import CardSchedule
from datetime import datetime, timezone


async def list_decks(db: AsyncSession) -> List[Deck]:
    result = await db.execute(
        select(Deck).where(Deck.deleted_at.is_(None)).order_by(Deck.created_at.desc())
    )
    return list(result.scalars().all())


async def get_deck(db: AsyncSession, deck_id: int) -> Optional[Deck]:
    result = await db.execute(
        select(Deck).where(Deck.id == deck_id, Deck.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def create_deck(db: AsyncSession, name: str, description: Optional[str] = None) -> Deck:
    deck = Deck(name=name, description=description)
    db.add(deck)
    await db.flush()
    return deck


async def update_deck(db: AsyncSession, deck: Deck, **kwargs) -> Deck:
    for key, value in kwargs.items():
        setattr(deck, key, value)
    await db.flush()
    return deck


async def delete_deck(db: AsyncSession, deck: Deck) -> None:
    deck.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def get_deck_stats(db: AsyncSession, deck_id: int) -> dict:
    now = datetime.now(timezone.utc)

    card_count = await db.scalar(
        select(func.count(Card.id)).where(Card.deck_id == deck_id)
    )

    due_count = await db.scalar(
        select(func.count(CardSchedule.id))
        .join(Card, Card.id == CardSchedule.card_id)
        .where(
            Card.deck_id == deck_id,
            CardSchedule.fsrs_due <= now,
        )
    )

    new_count = await db.scalar(
        select(func.count(CardSchedule.id))
        .join(Card, Card.id == CardSchedule.card_id)
        .where(
            Card.deck_id == deck_id,
            CardSchedule.fsrs_state == "new",
        )
    )

    return {
        "card_count": card_count or 0,
        "due_count": (due_count or 0) + (new_count or 0),
    }
