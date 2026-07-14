import json
from typing import List, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from src.db.models.card import Card
from src.db.models.card_schedule import CardSchedule
from src.db.models.deck import Deck
from src.db.models.tag import Tag, CardTag
from src.utils.thai_analysis import analyze_thai
from datetime import datetime, timedelta, timezone


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
    _embed: bool = True,
) -> Card:
    from src.db.services import embedding_service
    analysis = analyze_thai(thai)
    card = Card(
        deck_id=deck_id,
        thai=thai,
        english=english,
        romanization=romanization,
        example_thai=example_thai,
        example_english=example_english,
        card_type=card_type,
        source_upload_id=source_upload_id,
        syllable_count=analysis["syllable_count"],
        tone_pattern=json.dumps(analysis["tone_pattern"], ensure_ascii=False),
        consonant_classes=json.dumps(analysis["consonant_classes"], ensure_ascii=False),
        has_cluster=analysis["has_cluster"],
        has_rare_consonant=analysis["has_rare_consonant"],
        has_silent_mark=analysis["has_silent_mark"],
        script_analysis=json.dumps(analysis["script_analysis"], ensure_ascii=False),
    )
    db.add(card)
    try:
        await db.flush()
    except IntegrityError:
        # (deck_id, thai) already exists — return the existing card unchanged.
        await db.rollback()
        existing = await db.scalar(
            select(Card).where(Card.deck_id == deck_id, Card.thai == thai)
        )
        return existing

    # Create default th_to_en schedule
    schedule = CardSchedule(card_id=card.id, direction="th_to_en")
    db.add(schedule)
    await db.flush()

    if _embed:
        await embedding_service.embed_card(db, card.id)
    return card


async def bulk_create_cards(db: AsyncSession, deck_id: int, cards_data: list, source_upload_id: Optional[int] = None) -> List[Card]:
    from src.db.services import embedding_service

    # Deduplicate against cards already in the deck (keyed on Thai text).
    incoming_thai = [d["thai"].strip() for d in cards_data]
    existing_result = await db.execute(
        select(Card.thai).where(Card.deck_id == deck_id, Card.thai.in_(incoming_thai))
    )
    existing_thai = {row[0] for row in existing_result.all()}

    cards = []
    for data in cards_data:
        if data["thai"].strip() in existing_thai:
            continue
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
            _embed=False,  # embed all at once below via one batch model call
        )
        cards.append(card)
        existing_thai.add(data["thai"].strip())  # guard against duplicates within the same batch
    await embedding_service.embed_cards_batch(db, [c.id for c in cards])
    return cards


async def update_card(db: AsyncSession, card: Card, **kwargs) -> Card:
    from src.db.services import embedding_service
    content_fields = {"thai", "english", "example_thai"}
    content_changed = any(k in content_fields for k in kwargs)
    for key, value in kwargs.items():
        setattr(card, key, value)
    await db.flush()
    if content_changed:
        # Re-embed if text changed; text_hash check makes this a no-op if unchanged
        await embedding_service.embed_card(db, card.id)
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
    from src.db.services import embedding_service
    name = name.strip().lower()
    tag = await db.scalar(select(Tag).where(Tag.name == name))
    if not tag:
        tag = Tag(name=name)
        db.add(tag)
        await db.flush()
        await embedding_service.embed_tag(db, tag.id)
    return tag


async def add_tag_to_card(db: AsyncSession, card_id: int, tag_name: str) -> None:
    tag = await get_or_create_tag(db, tag_name)
    existing = await db.scalar(
        select(CardTag).where(CardTag.card_id == card_id, CardTag.tag_id == tag.id)
    )
    if not existing:
        db.add(CardTag(card_id=card_id, tag_id=tag.id))
        await db.flush()


async def get_due_cards_for_topic(
    db: AsyncSession, topic_id: int, limit: int = 20, direction: str = "th_to_en"
) -> List[tuple[Card, CardSchedule]]:
    """Return up to `limit` due or new cards in a topic (across all decks), ordered by due date."""
    from src.db.models.topic import CardTopic
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Card, CardSchedule)
        .join(CardTopic, CardTopic.card_id == Card.id)
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(
            CardTopic.topic_id == topic_id,
            CardSchedule.direction == direction,
            (CardSchedule.fsrs_due <= now) | (CardSchedule.fsrs_state == "new"),
        )
        .order_by(
            (CardSchedule.fsrs_state == "new").asc(),
            CardSchedule.fsrs_due.asc(),
        )
        .limit(limit)
    )
    return [(row[0], row[1]) for row in result.all()]


async def get_due_cards_library_wide(
    db: AsyncSession, limit: int = 50, direction: str = "th_to_en"
) -> List[tuple[Card, CardSchedule]]:
    """Due or new cards across the whole library, ordered by due date (new cards last)."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Card, CardSchedule)
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(
            CardSchedule.direction == direction,
            (CardSchedule.fsrs_due <= now) | (CardSchedule.fsrs_state == "new"),
        )
        .order_by(
            (CardSchedule.fsrs_state == "new").asc(),
            CardSchedule.fsrs_due.asc(),
        )
        .limit(limit)
    )
    return [(row[0], row[1]) for row in result.all()]


async def get_at_risk_card_pairs(
    db: AsyncSession,
    limit: int = 20,
    difficulty_threshold: float = 7.0,
    overdue_days: int = 14,
    direction: str = "th_to_en",
) -> List[tuple[Card, CardSchedule]]:
    """High-difficulty + significantly overdue cards as (Card, CardSchedule) pairs."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=overdue_days)
    result = await db.execute(
        select(Card, CardSchedule)
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(
            CardSchedule.direction == direction,
            CardSchedule.fsrs_difficulty >= difficulty_threshold,
            CardSchedule.fsrs_due <= cutoff,
            CardSchedule.fsrs_difficulty.isnot(None),
        )
        .order_by(CardSchedule.fsrs_difficulty.desc())
        .limit(limit)
    )
    return [(row[0], row[1]) for row in result.all()]


async def get_due_summary(db: AsyncSession) -> dict:
    """Library-wide due/new counts and top-5 breakdowns by deck and topic."""
    from src.db.models.topic import CardTopic, Topic
    now = datetime.now(timezone.utc)
    ago_7 = now - timedelta(days=7)
    ago_30 = now - timedelta(days=30)

    new_count = await db.scalar(
        select(func.count(CardSchedule.id))
        .where(CardSchedule.fsrs_state == "new")
    ) or 0

    due_today = await db.scalar(
        select(func.count(CardSchedule.id))
        .where(
            CardSchedule.fsrs_state != "new",
            CardSchedule.fsrs_due <= now,
        )
    ) or 0

    overdue_7d = await db.scalar(
        select(func.count(CardSchedule.id))
        .where(
            CardSchedule.fsrs_state != "new",
            CardSchedule.fsrs_due <= ago_7,
        )
    ) or 0

    overdue_30d = await db.scalar(
        select(func.count(CardSchedule.id))
        .where(
            CardSchedule.fsrs_state != "new",
            CardSchedule.fsrs_due <= ago_30,
        )
    ) or 0

    deck_rows = await db.execute(
        select(
            Deck.id.label("deck_id"),
            Deck.name.label("deck_name"),
            func.count(CardSchedule.id).label("due_count"),
        )
        .join(Card, Card.deck_id == Deck.id)
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(
            (CardSchedule.fsrs_due <= now) | (CardSchedule.fsrs_state == "new")
        )
        .where(Deck.deleted_at.is_(None))
        .group_by(Deck.id, Deck.name)
        .order_by(func.count(CardSchedule.id).desc())
        .limit(5)
    )
    by_deck = [
        {"deck_id": r.deck_id, "deck_name": r.deck_name, "due_count": r.due_count}
        for r in deck_rows
    ]

    topic_rows = await db.execute(
        select(
            Topic.id.label("topic_id"),
            Topic.name.label("topic_name"),
            func.count(CardSchedule.id.distinct()).label("due_count"),
        )
        .join(CardTopic, CardTopic.topic_id == Topic.id)
        .join(Card, Card.id == CardTopic.card_id)
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(
            (CardSchedule.fsrs_due <= now) | (CardSchedule.fsrs_state == "new")
        )
        .group_by(Topic.id, Topic.name)
        .order_by(func.count(CardSchedule.id.distinct()).desc())
        .limit(5)
    )
    by_topic = [
        {"topic_id": r.topic_id, "topic_name": r.topic_name, "due_count": r.due_count}
        for r in topic_rows
    ]

    return {
        "total_due": due_today + new_count,
        "due_today": due_today,
        "new_cards": new_count,
        "overdue_by_7d": overdue_7d,
        "overdue_by_30d": overdue_30d,
        "by_deck": by_deck,
        "by_topic": by_topic,
    }
