from typing import List, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.card import Card
from src.db.models.card_schedule import CardSchedule
from src.db.models.tag import Tag, CardTag
from datetime import datetime, timezone


async def get_cards_for_deck(
    db: AsyncSession, deck_id: int, offset: int = 0, limit: int = 50
) -> List[Card]:
    result = await db.execute(
        select(Card)
        .where(Card.deck_id == deck_id)
        .order_by(Card.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_cards_for_deck(db: AsyncSession, deck_id: int) -> int:
    result = await db.execute(select(func.count()).where(Card.deck_id == deck_id))
    return result.scalar_one()


async def get_card(db: AsyncSession, card_id: int) -> Optional[Card]:
    return await db.get(Card, card_id)


async def create_card(
    db: AsyncSession,
    deck_id: int,
    thai: str,
    english: str,
    romanization: Optional[str] = None,
    example_thai: Optional[str] = None,
    example_english: Optional[str] = None,
    card_type: str = "vocab",
    source_upload_id: Optional[int] = None,
) -> Card:
    card = Card(
        deck_id=deck_id,
        thai=thai,
        english=english,
        romanization=romanization,
        example_thai=example_thai,
        example_english=example_english,
        card_type=card_type,
        source_upload_id=source_upload_id,
    )
    db.add(card)
    await db.flush()

    # Create default th_to_en schedule
    schedule = CardSchedule(card_id=card.id, direction="th_to_en")
    db.add(schedule)
    await db.flush()
    return card


async def bulk_create_cards(db: AsyncSession, deck_id: int, cards_data: list, source_upload_id: Optional[int] = None) -> List[Card]:
    cards = []
    for data in cards_data:
        card = await create_card(
            db,
            deck_id=deck_id,
            thai=data["thai"],
            english=data["english"],
            romanization=data.get("romanization"),
            example_thai=data.get("example_thai"),
            example_english=data.get("example_english"),
            card_type=data.get("card_type", "vocab"),
            source_upload_id=source_upload_id,
        )
        cards.append(card)
    return cards


async def update_card(db: AsyncSession, card: Card, **kwargs) -> Card:
    for key, value in kwargs.items():
        setattr(card, key, value)
    await db.flush()
    return card


async def delete_card(db: AsyncSession, card: Card) -> None:
    await db.delete(card)
    await db.flush()


async def get_due_cards(
    db: AsyncSession, deck_id: int, limit: int = 20, direction: str = "th_to_en"
) -> List[tuple[Card, CardSchedule]]:
    """Return up to `limit` due or new cards for review, ordered by due date."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Card, CardSchedule)
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(
            Card.deck_id == deck_id,
            CardSchedule.direction == direction,
            (CardSchedule.fsrs_due <= now) | (CardSchedule.fsrs_state == "new"),
        )
        .order_by(
            # New cards last (learn review-due cards first)
            (CardSchedule.fsrs_state == "new").asc(),
            CardSchedule.fsrs_due.asc(),
        )
        .limit(limit)
    )
    return [(row[0], row[1]) for row in result.all()]


async def get_or_create_tag(db: AsyncSession, name: str) -> Tag:
    name = name.strip().lower()
    tag = await db.scalar(select(Tag).where(Tag.name == name))
    if not tag:
        tag = Tag(name=name)
        db.add(tag)
        await db.flush()
    return tag


async def add_tag_to_card(db: AsyncSession, card_id: int, tag_name: str) -> None:
    tag = await get_or_create_tag(db, tag_name)
    existing = await db.scalar(
        select(CardTag).where(CardTag.card_id == card_id, CardTag.tag_id == tag.id)
    )
    if not existing:
        db.add(CardTag(card_id=card_id, tag_id=tag.id))
        await db.flush()
