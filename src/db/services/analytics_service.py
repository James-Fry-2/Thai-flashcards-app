from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy import select, func, and_, not_, exists
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.card import Card
from src.db.models.card_schedule import CardSchedule
from src.db.models.deck import Deck
from src.db.models.tag import CardTag

_UTC = timezone.utc


async def get_untagged_cards(
    db: AsyncSession, deck_id: Optional[int] = None
) -> list[dict]:
    """Cards that have no tags, optionally filtered to a single deck."""
    stmt = select(Card).where(
        not_(exists(select(CardTag.card_id).where(CardTag.card_id == Card.id)))
    )
    if deck_id is not None:
        stmt = stmt.where(Card.deck_id == deck_id)
    stmt = stmt.order_by(Card.created_at.desc())
    result = await db.execute(stmt)
    return [_card_summary(c) for c in result.scalars().all()]


async def get_card_type_distribution(
    db: AsyncSession, deck_id: Optional[int] = None
) -> dict:
    """Count of cards per card_type (vocab / phrase / grammar)."""
    stmt = select(Card.card_type, func.count(Card.id).label("count"))
    if deck_id is not None:
        stmt = stmt.where(Card.deck_id == deck_id)
    stmt = stmt.group_by(Card.card_type)
    result = await db.execute(stmt)
    return {row.card_type: row.count for row in result}


async def get_fsrs_summary(
    db: AsyncSession, deck_id: Optional[int] = None
) -> list[dict]:
    """
    Average FSRS difficulty and stability, grouped by card_type and fsrs_state.
    Only includes schedules that have been reviewed at least once (difficulty is not null).
    """
    stmt = (
        select(
            Card.card_type,
            CardSchedule.fsrs_state,
            func.count(CardSchedule.id).label("count"),
            func.avg(CardSchedule.fsrs_difficulty).label("avg_difficulty"),
            func.avg(CardSchedule.fsrs_stability).label("avg_stability"),
            func.avg(CardSchedule.fsrs_lapses).label("avg_lapses"),
        )
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(CardSchedule.fsrs_difficulty.isnot(None))
    )
    if deck_id is not None:
        stmt = stmt.where(Card.deck_id == deck_id)
    stmt = stmt.group_by(Card.card_type, CardSchedule.fsrs_state)
    result = await db.execute(stmt)
    rows = result.all()
    return [
        {
            "card_type": row.card_type,
            "fsrs_state": row.fsrs_state,
            "count": row.count,
            "avg_difficulty": round(row.avg_difficulty, 3) if row.avg_difficulty else None,
            "avg_stability": round(row.avg_stability, 3) if row.avg_stability else None,
            "avg_lapses": round(row.avg_lapses, 2) if row.avg_lapses else None,
        }
        for row in rows
    ]


async def get_deck_coverage(db: AsyncSession) -> list[dict]:
    """
    Per-deck health metrics: card count, tagged/untagged split, new/due card counts.
    Excludes soft-deleted decks.
    """
    # Total cards per deck
    total_stmt = (
        select(Card.deck_id, func.count(Card.id).label("total"))
        .group_by(Card.deck_id)
        .subquery()
    )

    # Tagged cards per deck (cards that appear in card_tags at least once)
    tagged_stmt = (
        select(Card.deck_id, func.count(Card.id.distinct()).label("tagged"))
        .join(CardTag, CardTag.card_id == Card.id)
        .group_by(Card.deck_id)
        .subquery()
    )

    # New (never reviewed) card schedules per deck
    new_stmt = (
        select(Card.deck_id, func.count(CardSchedule.id).label("new_count"))
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(CardSchedule.fsrs_state == "new")
        .group_by(Card.deck_id)
        .subquery()
    )

    # Due (review state, due <= now) per deck
    now = datetime.now(_UTC)
    due_stmt = (
        select(Card.deck_id, func.count(CardSchedule.id).label("due_count"))
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(
            and_(
                CardSchedule.fsrs_state.in_(["review", "learning", "relearning"]),
                CardSchedule.fsrs_due <= now,
            )
        )
        .group_by(Card.deck_id)
        .subquery()
    )

    stmt = (
        select(
            Deck.id,
            Deck.name,
            func.coalesce(total_stmt.c.total, 0).label("total"),
            func.coalesce(tagged_stmt.c.tagged, 0).label("tagged"),
            func.coalesce(new_stmt.c.new_count, 0).label("new_count"),
            func.coalesce(due_stmt.c.due_count, 0).label("due_count"),
        )
        .outerjoin(total_stmt, total_stmt.c.deck_id == Deck.id)
        .outerjoin(tagged_stmt, tagged_stmt.c.deck_id == Deck.id)
        .outerjoin(new_stmt, new_stmt.c.deck_id == Deck.id)
        .outerjoin(due_stmt, due_stmt.c.deck_id == Deck.id)
        .where(Deck.deleted_at.is_(None))
        .order_by(Deck.name)
    )
    result = await db.execute(stmt)
    return [
        {
            "deck_id": row.id,
            "deck_name": row.name,
            "total_cards": row.total,
            "tagged_cards": row.tagged,
            "untagged_cards": row.total - row.tagged,
            "new_cards": row.new_count,
            "due_cards": row.due_count,
        }
        for row in result
    ]


async def get_at_risk_cards(
    db: AsyncSession,
    deck_id: Optional[int] = None,
    limit: int = 20,
    difficulty_threshold: float = 7.0,
    overdue_days: int = 14,
) -> list[dict]:
    """
    Cards with high FSRS difficulty that are significantly overdue.
    These are the highest-risk items for forgetting.
    """
    cutoff = datetime.now(_UTC) - timedelta(days=overdue_days)
    stmt = (
        select(Card, CardSchedule)
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(
            and_(
                CardSchedule.fsrs_difficulty >= difficulty_threshold,
                CardSchedule.fsrs_due <= cutoff,
                CardSchedule.fsrs_difficulty.isnot(None),
            )
        )
        .order_by(CardSchedule.fsrs_difficulty.desc())
        .limit(limit)
    )
    if deck_id is not None:
        stmt = stmt.where(Card.deck_id == deck_id)
    result = await db.execute(stmt)
    rows = result.all()
    return [
        {
            **_card_summary(row.Card),
            "fsrs_difficulty": row.CardSchedule.fsrs_difficulty,
            "fsrs_stability": row.CardSchedule.fsrs_stability,
            "fsrs_state": row.CardSchedule.fsrs_state,
            "fsrs_lapses": row.CardSchedule.fsrs_lapses,
            "fsrs_due": row.CardSchedule.fsrs_due.isoformat() if row.CardSchedule.fsrs_due else None,
            "direction": row.CardSchedule.direction,
        }
        for row in rows
    ]


def _card_summary(card: Card) -> dict:
    return {
        "id": card.id,
        "deck_id": card.deck_id,
        "thai": card.thai,
        "english": card.english,
        "card_type": card.card_type,
        "created_at": card.created_at.isoformat(),
    }
