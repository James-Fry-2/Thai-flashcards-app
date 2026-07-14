import re
from typing import Optional
from sqlalchemy import select, func, and_, not_, exists
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.card import Card
from src.db.models.card_schedule import CardSchedule
from src.db.models.deck import Deck
from src.db.models.topic import Topic, CardTopic
from src.db.models.base import utcnow


def _normalize_name(name: str) -> str:
    n = name.strip().lower()
    n = re.sub(r'[^\w\s]', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    if n.endswith('s') and len(n) > 2:
        n = n[:-1]
    return n


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for ca in a:
        curr = [prev[0] + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j] + (0 if ca == cb else 1), prev[j + 1] + 1, curr[j] + 1))
        prev = curr
    return prev[-1]


def _is_contained_word(shorter: str, longer: str) -> bool:
    return bool(re.search(r'\b' + re.escape(shorter) + r'\b', longer, re.IGNORECASE))


async def list_topics(
    db: AsyncSession,
    parent_id: Optional[int] = None,
    has_due: bool = False,
) -> list[dict]:
    """
    List topics with per-topic card counts and average FSRS difficulty.
    Pass parent_id to drill into subtopics; omit for all topics.
    Pass has_due=True to restrict to topics with at least one new or due card.
    """
    now = utcnow()

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
    new_subq = (
        select(CardTopic.topic_id, func.count(CardSchedule.id).label("new_count"))
        .join(Card, Card.id == CardTopic.card_id)
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(CardSchedule.fsrs_state == "new")
        .group_by(CardTopic.topic_id)
        .subquery()
    )
    due_subq = (
        select(CardTopic.topic_id, func.count(CardSchedule.id).label("due_count"))
        .join(Card, Card.id == CardTopic.card_id)
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(CardSchedule.fsrs_due <= now)
        .group_by(CardTopic.topic_id)
        .subquery()
    )

    stmt = (
        select(
            Topic,
            func.coalesce(count_subq.c.card_count, 0).label("card_count"),
            diff_subq.c.avg_difficulty,
            func.coalesce(new_subq.c.new_count, 0).label("new_count"),
            func.coalesce(due_subq.c.due_count, 0).label("due_count"),
        )
        .outerjoin(count_subq, count_subq.c.topic_id == Topic.id)
        .outerjoin(diff_subq, diff_subq.c.topic_id == Topic.id)
        .outerjoin(new_subq, new_subq.c.topic_id == Topic.id)
        .outerjoin(due_subq, due_subq.c.topic_id == Topic.id)
        .order_by(Topic.sort_order, Topic.name)
    )
    if parent_id is not None:
        stmt = stmt.where(Topic.parent_id == parent_id)
    if has_due:
        stmt = stmt.where(
            (func.coalesce(new_subq.c.new_count, 0) + func.coalesce(due_subq.c.due_count, 0)) > 0
        )

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
            "new_count": row.new_count,
            "due_count": row.due_count,
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


async def count_cards_by_topic(
    db: AsyncSession,
    topic_id: int,
    card_type: Optional[str] = None,
    fsrs_state: Optional[str] = None,
) -> int:
    stmt = (
        select(func.count(Card.id))
        .join(CardTopic, CardTopic.card_id == Card.id)
        .where(CardTopic.topic_id == topic_id)
    )
    if card_type:
        stmt = stmt.where(Card.card_type == card_type)
    if fsrs_state:
        stmt = stmt.join(CardSchedule, CardSchedule.card_id == Card.id).where(
            CardSchedule.fsrs_state == fsrs_state
        )
    return await db.scalar(stmt) or 0


async def get_topic_summary(db: AsyncSession, topic_id: int) -> Optional[dict]:
    """
    Returns aggregated summary for the browse panel.
    Three queries: counts, decks_represented, card_type_breakdown.
    """
    topic = await db.get(Topic, topic_id)
    if not topic:
        return None

    now = utcnow()

    card_count = await db.scalar(
        select(func.count(CardTopic.card_id)).where(CardTopic.topic_id == topic_id)
    )

    new_count = await db.scalar(
        select(func.count(CardSchedule.id))
        .join(Card, Card.id == CardSchedule.card_id)
        .join(CardTopic, CardTopic.card_id == Card.id)
        .where(CardTopic.topic_id == topic_id, CardSchedule.fsrs_state == "new")
    )

    due_count = await db.scalar(
        select(func.count(CardSchedule.id))
        .join(Card, Card.id == CardSchedule.card_id)
        .join(CardTopic, CardTopic.card_id == Card.id)
        .where(CardTopic.topic_id == topic_id, CardSchedule.fsrs_due <= now)
    )

    decks_result = await db.execute(
        select(
            Deck.id.label("deck_id"),
            Deck.name.label("deck_name"),
            func.count(Card.id).label("card_count"),
        )
        .join(Card, Card.deck_id == Deck.id)
        .join(CardTopic, CardTopic.card_id == Card.id)
        .where(CardTopic.topic_id == topic_id)
        .group_by(Deck.id, Deck.name)
        .order_by(func.count(Card.id).desc())
        .limit(5)
    )
    decks_represented = [
        {"deck_id": row.deck_id, "deck_name": row.deck_name, "card_count": row.card_count}
        for row in decks_result
    ]

    breakdown_result = await db.execute(
        select(Card.card_type, func.count(Card.id).label("count"))
        .join(CardTopic, CardTopic.card_id == Card.id)
        .where(CardTopic.topic_id == topic_id)
        .group_by(Card.card_type)
    )
    card_type_breakdown = {row.card_type: row.count for row in breakdown_result}

    return {
        "id": topic.id,
        "name": topic.name,
        "description": topic.description,
        "parent_id": topic.parent_id,
        "card_count": card_count or 0,
        "new_count": new_count or 0,
        "due_count": due_count or 0,
        "decks_represented": decks_represented,
        "card_type_breakdown": card_type_breakdown,
    }


async def get_or_create_topic(db: AsyncSession, name: str) -> Topic:
    from src.db.services import embedding_service
    normalized = name.strip()
    topic = await db.scalar(
        select(Topic).where(func.lower(Topic.name) == func.lower(normalized))
    )
    if not topic:
        topic = await create_topic(db, name=normalized, sort_order=0, _embed=False)
        await embedding_service.embed_topic(db, topic.id)
    return topic


async def create_topic(
    db: AsyncSession,
    name: str,
    description: Optional[str] = None,
    parent_id: Optional[int] = None,
    sort_order: int = 0,
    _embed: bool = True,
) -> Topic:
    from src.db.services import embedding_service
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
    if _embed:
        await embedding_service.embed_topic(db, topic.id)
    return topic


async def update_topic(
    db: AsyncSession,
    topic: Topic,
    name: Optional[str] = None,
    description: Optional[str] = None,
    parent_id: Optional[int] = None,
    sort_order: Optional[int] = None,
) -> Topic:
    from src.db.services import embedding_service
    text_changed = name is not None or description is not None
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
    if text_changed:
        await embedding_service.embed_topic(db, topic.id)
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


async def merge_topics(db: AsyncSession, source_id: int, target_id: int) -> dict:
    from src.db.services import embedding_service
    source = await db.get(Topic, source_id)
    target = await db.get(Topic, target_id)

    # Fix dangling FK: if target's parent points to source, null it before we delete source
    if target.parent_id == source_id:
        target.parent_id = None
        await db.flush()

    target_existing_result = await db.execute(
        select(CardTopic.card_id).where(CardTopic.topic_id == target_id)
    )
    already_in_target = {row[0] for row in target_existing_result}

    source_ct_result = await db.execute(
        select(CardTopic).where(CardTopic.topic_id == source_id)
    )
    source_cts = source_ct_result.scalars().all()

    cards_moved = 0
    cards_already_present = 0

    for ct in source_cts:
        if ct.card_id in already_in_target:
            await db.delete(ct)
            cards_already_present += 1
        else:
            ct.topic_id = target_id
            cards_moved += 1

    await db.flush()

    if not target.description and source.description:
        target.description = source.description
    if target.parent_id is None and source.parent_id is not None:
        if source.parent_id != target.id:
            target.parent_id = source.parent_id
    target.updated_at = utcnow()
    await db.flush()

    await db.delete(source)
    await db.flush()

    # Re-embed target since description/parent may have changed during merge
    await embedding_service.embed_topic(db, target_id, force=True)

    return {
        "merged": True,
        "target_id": target_id,
        "cards_moved": cards_moved,
        "cards_already_present": cards_already_present,
    }


async def find_potential_duplicates(db: AsyncSession, embedding_threshold: float = 0.85) -> list[dict]:
    from src.db.services import embedding_service

    count_subq = (
        select(CardTopic.topic_id, func.count(CardTopic.card_id).label("card_count"))
        .group_by(CardTopic.topic_id)
        .subquery()
    )
    stmt = (
        select(Topic, func.coalesce(count_subq.c.card_count, 0).label("card_count"))
        .outerjoin(count_subq, count_subq.c.topic_id == Topic.id)
        .order_by(Topic.name)
    )
    result = await db.execute(stmt)
    topics = [
        {"id": row.Topic.id, "name": row.Topic.name, "card_count": row.card_count}
        for row in result
    ]

    # pairs keyed by (min_id, max_id); value holds reasons list and max score
    pairs: dict[tuple[int, int], dict] = {}

    def _add_pair(a: dict, b: dict, reason: str, score: float) -> None:
        key = (min(a["id"], b["id"]), max(a["id"], b["id"]))
        lo = a if a["id"] < b["id"] else b
        hi = b if a["id"] < b["id"] else a
        if key not in pairs:
            pairs[key] = {"topic_a": lo, "topic_b": hi, "reasons": [reason], "score": score}
        else:
            if reason not in pairs[key]["reasons"]:
                pairs[key]["reasons"].append(reason)
            pairs[key]["score"] = max(pairs[key]["score"], score)

    # Deterministic rules (score=1.0 — high confidence)
    for i, a in enumerate(topics):
        a_norm = _normalize_name(a["name"])
        for b in topics[i + 1:]:
            b_norm = _normalize_name(b["name"])
            if a_norm == b_norm:
                _add_pair(a, b, "same normalized name", 1.0)
            elif _levenshtein(a_norm, b_norm) <= 2:
                dist = _levenshtein(a_norm, b_norm)
                _add_pair(a, b, f"similar name (edit distance {dist})", 1.0)
            else:
                a_lower = a["name"].lower()
                b_lower = b["name"].lower()
                if len(a_lower) != len(b_lower):
                    shorter = a_lower if len(a_lower) < len(b_lower) else b_lower
                    longer = b_lower if len(a_lower) < len(b_lower) else a_lower
                    if _is_contained_word(shorter, longer):
                        _add_pair(a, b, "one name contains the other", 1.0)

    # Embedding-based detection (additive)
    topic_by_id = {t["id"]: t for t in topics}
    emb_pairs = await embedding_service.find_duplicate_topic_candidates(
        db, min_similarity=embedding_threshold
    )
    for ep in emb_pairs:
        a = topic_by_id.get(ep["topic_a"]["id"])
        b = topic_by_id.get(ep["topic_b"]["id"])
        if a and b:
            sim = ep["similarity"]
            _add_pair(a, b, f"embedding similarity: {sim:.2f}", sim)

    # Flatten: join reasons into a single string
    output = []
    for p in pairs.values():
        output.append({
            "topic_a": p["topic_a"],
            "topic_b": p["topic_b"],
            "reason": "; ".join(p["reasons"]),
            "score": p["score"],
        })

    return sorted(output, key=lambda p: p["score"], reverse=True)
