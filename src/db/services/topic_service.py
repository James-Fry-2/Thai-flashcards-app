from typing import Optional
from sqlalchemy import select, func, and_, not_, exists
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.card import Card
from src.db.models.card_schedule import CardSchedule
from src.db.models.deck import Deck
from src.db.models.topic import Topic, CardTopic
from src.db.models.base import utcnow


async def list_topics(
    db: AsyncSession, parent_id: Optional[int] = None
) -> list[dict]:
    """
    List topics with per-topic card counts and average FSRS difficulty.
    Pass parent_id to drill into subtopics; omit for all topics.
    """
    count_subq = (
        select(CardTopic.topic_id, func.count(CardTopic.card_id).label("card_count"))
        .group_by(CardTopic.topic_id)
        .subquery()
    )
    diff_subq = (
        select(
            CardTopic.topic_id,
            func.avg(CardSchedule.fsrs_difficulty).label("avg_difficulty"),
        )
        .join(Card, Card.id == CardTopic.card_id)
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(CardSchedule.fsrs_difficulty.isnot(None))
        .group_by(CardTopic.topic_id)
        .subquery()
    )

    stmt = (
        select(
            Topic,
            func.coalesce(count_subq.c.card_count, 0).label("card_count"),
            diff_subq.c.avg_difficulty,
        )
        .outerjoin(count_subq, count_subq.c.topic_id == Topic.id)
        .outerjoin(diff_subq, diff_subq.c.topic_id == Topic.id)
        .order_by(Topic.sort_order, Topic.name)
    )
    if parent_id is not None:
        stmt = stmt.where(Topic.parent_id == parent_id)

    result = await db.execute(stmt)
    return [
        {
            "id": row.Topic.id,
            "name": row.Topic.name,
            "description": row.Topic.description,
            "parent_id": row.Topic.parent_id,
            "sort_order": row.Topic.sort_order,
            "card_count": row.card_count,
            "avg_fsrs_difficulty": round(row.avg_difficulty, 3) if row.avg_difficulty else None,
        }
        for row in result
    ]


async def get_topic_tree(db: AsyncSession) -> list[dict]:
    """Return all topics as a nested tree (root nodes with recursive children)."""
    count_subq = (
        select(CardTopic.topic_id, func.count(CardTopic.card_id).label("card_count"))
        .group_by(CardTopic.topic_id)
        .subquery()
    )
    stmt = (
        select(Topic, func.coalesce(count_subq.c.card_count, 0).label("card_count"))
        .outerjoin(count_subq, count_subq.c.topic_id == Topic.id)
        .order_by(Topic.sort_order, Topic.name)
    )
    result = await db.execute(stmt)
    rows = result.all()

    by_id: dict[int, dict] = {}
    for row in rows:
        by_id[row.Topic.id] = {
            "id": row.Topic.id,
            "name": row.Topic.name,
            "description": row.Topic.description,
            "parent_id": row.Topic.parent_id,
            "sort_order": row.Topic.sort_order,
            "card_count": row.card_count,
            "children": [],
        }

    roots: list[dict] = []
    for node in by_id.values():
        if node["parent_id"] is None:
            roots.append(node)
        elif node["parent_id"] in by_id:
            by_id[node["parent_id"]]["children"].append(node)

    return roots


async def get_topic(db: AsyncSession, topic_id: int) -> Optional[Topic]:
    return await db.get(Topic, topic_id)


async def get_cards_by_topic(
    db: AsyncSession,
    topic_id: int,
    offset: int = 0,
    limit: int = 50,
    card_type: Optional[str] = None,
    fsrs_state: Optional[str] = None,
) -> list[dict]:
    """Paginated cards in a topic (across all decks)."""
    stmt = (
        select(Card)
        .join(CardTopic, CardTopic.card_id == Card.id)
        .where(CardTopic.topic_id == topic_id)
    )
    if card_type:
        stmt = stmt.where(Card.card_type == card_type)
    if fsrs_state:
        stmt = stmt.join(CardSchedule, CardSchedule.card_id == Card.id).where(
            CardSchedule.fsrs_state == fsrs_state
        )
    stmt = stmt.order_by(Card.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return [_card_summary(c) for c in result.scalars().all()]


async def create_topic(
    db: AsyncSession,
    name: str,
    description: Optional[str] = None,
    parent_id: Optional[int] = None,
    sort_order: int = 0,
) -> Topic:
    now = utcnow()
    topic = Topic(
        name=name,
        description=description,
        parent_id=parent_id,
        sort_order=sort_order,
        created_at=now,
        updated_at=now,
    )
    db.add(topic)
    await db.flush()
    return topic


async def update_topic(
    db: AsyncSession,
    topic: Topic,
    name: Optional[str] = None,
    description: Optional[str] = None,
    parent_id: Optional[int] = None,
    sort_order: Optional[int] = None,
) -> Topic:
    if name is not None:
        topic.name = name
    if description is not None:
        topic.description = description
    if parent_id is not None:
        topic.parent_id = parent_id
    if sort_order is not None:
        topic.sort_order = sort_order
    topic.updated_at = utcnow()
    await db.flush()
    return topic


async def delete_topic(db: AsyncSession, topic: Topic) -> None:
    await db.delete(topic)
    await db.flush()


async def assign_cards(
    db: AsyncSession, topic_id: int, card_ids: list[int]
) -> int:
    """
    Bulk-assign cards to a topic. Skips card_ids already assigned.
    Returns the number of new assignments created.
    """
    # Find which cards are already in this topic
    existing = await db.execute(
        select(CardTopic.card_id).where(
            CardTopic.topic_id == topic_id,
            CardTopic.card_id.in_(card_ids),
        )
    )
    existing_ids = {row[0] for row in existing}
    new_ids = [cid for cid in card_ids if cid not in existing_ids]

    for cid in new_ids:
        db.add(CardTopic(card_id=cid, topic_id=topic_id))
    await db.flush()
    return len(new_ids)


async def remove_card(db: AsyncSession, topic_id: int, card_id: int) -> bool:
    """Remove a card from a topic. Returns True if removed, False if not found."""
    ct = await db.scalar(
        select(CardTopic).where(
            CardTopic.topic_id == topic_id, CardTopic.card_id == card_id
        )
    )
    if not ct:
        return False
    await db.delete(ct)
    await db.flush()
    return True


async def get_gap_report(db: AsyncSession) -> dict:
    """
    Comprehensive gap report for the topic layer:
    - topics_with_few_cards: topics with fewer than 5 cards
    - unassigned_cards_by_deck: cards belonging to no topic, grouped by deck
    - card_type_breakdown_by_topic: {topic_id: {vocab: N, phrase: N, grammar: N}}
    - fsrs_difficulty_by_topic: {topic_id: avg_difficulty}
    - topics_never_reviewed: topics where all cards are still in fsrs_state="new"
    """
    # --- Topics with few cards ---
    count_subq = (
        select(CardTopic.topic_id, func.count(CardTopic.card_id).label("card_count"))
        .group_by(CardTopic.topic_id)
        .subquery()
    )
    thin_result = await db.execute(
        select(Topic, func.coalesce(count_subq.c.card_count, 0).label("card_count"))
        .outerjoin(count_subq, count_subq.c.topic_id == Topic.id)
        .where(func.coalesce(count_subq.c.card_count, 0) < 5)
        .order_by(func.coalesce(count_subq.c.card_count, 0))
    )
    topics_with_few_cards = [
        {"id": row.Topic.id, "name": row.Topic.name, "card_count": row.card_count}
        for row in thin_result
    ]

    # --- Unassigned cards per deck ---
    unassigned_result = await db.execute(
        select(Card, Deck)
        .join(Deck, Deck.id == Card.deck_id)
        .where(
            not_(
                exists(select(CardTopic.card_id).where(CardTopic.card_id == Card.id))
            ),
            Deck.deleted_at.is_(None),
        )
        .order_by(Deck.name, Card.created_at.desc())
    )
    unassigned_by_deck: dict[str, list[dict]] = {}
    for row in unassigned_result:
        deck_name = row.Deck.name
        if deck_name not in unassigned_by_deck:
            unassigned_by_deck[deck_name] = []
        unassigned_by_deck[deck_name].append(_card_summary(row.Card))

    # --- Card type breakdown per topic ---
    breakdown_result = await db.execute(
        select(CardTopic.topic_id, Card.card_type, func.count(Card.id).label("count"))
        .join(Card, Card.id == CardTopic.card_id)
        .group_by(CardTopic.topic_id, Card.card_type)
    )
    type_breakdown: dict[int, dict] = {}
    for row in breakdown_result:
        if row.topic_id not in type_breakdown:
            type_breakdown[row.topic_id] = {}
        type_breakdown[row.topic_id][row.card_type] = row.count

    # --- FSRS difficulty per topic ---
    diff_result = await db.execute(
        select(
            CardTopic.topic_id,
            func.avg(CardSchedule.fsrs_difficulty).label("avg_diff"),
        )
        .join(Card, Card.id == CardTopic.card_id)
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(CardSchedule.fsrs_difficulty.isnot(None))
        .group_by(CardTopic.topic_id)
    )
    difficulty_by_topic: dict[int, float] = {
        row.topic_id: round(row.avg_diff, 3) for row in diff_result
    }

    # --- Topics never reviewed (all cards in state "new") ---
    # A topic is "never reviewed" if it has no card with a non-new schedule
    reviewed_topic_ids_result = await db.execute(
        select(CardTopic.topic_id)
        .join(Card, Card.id == CardTopic.card_id)
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(CardSchedule.fsrs_state != "new")
        .distinct()
    )
    reviewed_ids = {row[0] for row in reviewed_topic_ids_result}

    all_topic_ids_result = await db.execute(
        select(CardTopic.topic_id).distinct()
    )
    all_topic_ids = {row[0] for row in all_topic_ids_result}
    never_reviewed_ids = all_topic_ids - reviewed_ids

    never_reviewed = []
    if never_reviewed_ids:
        topics_result = await db.execute(
            select(Topic).where(Topic.id.in_(never_reviewed_ids)).order_by(Topic.name)
        )
        never_reviewed = [
            {"id": t.id, "name": t.name}
            for t in topics_result.scalars().all()
        ]

    return {
        "topics_with_few_cards": topics_with_few_cards,
        "unassigned_cards_by_deck": unassigned_by_deck,
        "card_type_breakdown_by_topic": {str(k): v for k, v in type_breakdown.items()},
        "fsrs_difficulty_by_topic": {str(k): v for k, v in difficulty_by_topic.items()},
        "topics_never_reviewed": never_reviewed,
    }


def _card_summary(card: Card) -> dict:
    return {
        "id": card.id,
        "deck_id": card.deck_id,
        "thai": card.thai,
        "english": card.english,
        "card_type": card.card_type,
        "created_at": card.created_at.isoformat(),
    }
