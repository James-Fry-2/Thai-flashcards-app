"""
Study-oriented search service.

Returns three tiers:
  groupings — real topics and tags matching the query (lexical + semantic), each studyable.
  ad_hoc    — the complete hybrid-matched card set (union of lexical + semantic), saveable/studyable.
  cards     — the same matched set enriched for the browse table (capped to limit_cards).

Ranking bands differ by context:
  Grouping names  — lexical 40–100, semantic 0–40 (name matches lead).
  Card browse     — lexical 40–100, semantic 0–30 (literal always above semantic).
"""
from typing import Optional

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.card import Card
from src.db.models.tag import Tag, CardTag
from src.db.models.topic import Topic, CardTopic
from src.db.models.deck import Deck
from src.db.services import embedding_service

HARD_MAX = 500


# ---------------------------------------------------------------------------
# Internal scoring helpers
# ---------------------------------------------------------------------------

def _name_score(name: str, q_lower: str) -> int:
    n = name.lower()
    if n == q_lower:
        return 100
    if n.startswith(q_lower):
        return 70
    if q_lower in n:
        return 40
    return 0


def _card_score(card: Card, q_lower: str) -> tuple[int, str]:
    """Return (lexical_score, match_type) for a card. 0 means no match."""
    best = 0
    for field in (card.thai, card.english, card.romanization, card.example_thai):
        if field:
            s = _name_score(field, q_lower)
            if s > best:
                best = s
    if best == 100:
        return 100, "exact"
    if best == 70:
        return 70, "prefix"
    if best >= 40:
        return 40, "substring"
    return 0, "none"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def study_search(
    db: AsyncSession,
    query: str,
    limit_cards: int = 200,
    deck_id: Optional[int] = None,
    card_type: Optional[str] = None,
) -> dict:
    empty: dict = {
        "query": query,
        "groupings": {"topics": [], "tags": []},
        "ad_hoc": {
            "card_ids": [],
            "total": 0,
            "topic_spread": [],
            "untagged_count": 0,
            "deck_spread": [],
            "truncated": False,
        },
        "cards": [],
    }

    q = query.strip()
    if not q:
        return empty

    cap = min(limit_cards, HARD_MAX)
    q_lower = q.lower()

    # Semantic searches (sequential; safe on a single AsyncSession)
    sem_topics = await embedding_service.search_topics_semantic(db, q)
    sem_tags = await embedding_service.search_tags_semantic(db, q)
    sem_cards = await embedding_service.search_cards_semantic(db, q, limit=cap, min_similarity=0.35)

    # -----------------------------------------------------------------------
    # GROUPINGS — topics
    # -----------------------------------------------------------------------
    topic_count_subq = (
        select(CardTopic.topic_id, func.count(CardTopic.card_id).label("card_count"))
        .group_by(CardTopic.topic_id)
        .subquery()
    )

    lex_topic_rows = await db.execute(
        select(Topic, func.coalesce(topic_count_subq.c.card_count, 0).label("card_count"))
        .outerjoin(topic_count_subq, topic_count_subq.c.topic_id == Topic.id)
        .where(Topic.name.ilike(f"%{q}%"))
    )

    topic_map: dict[int, dict] = {}
    for row in lex_topic_rows:
        t = row.Topic
        s = _name_score(t.name, q_lower)
        if s:
            topic_map[t.id] = {
                "id": t.id, "name": t.name, "card_count": row.card_count,
                "match_type": "lexical", "score": float(s),
            }

    # Load topics found semantically but not yet in map
    sem_topic_missing = [h["topic_id"] for h in sem_topics if h["topic_id"] not in topic_map]
    if sem_topic_missing:
        extra_rows = await db.execute(
            select(Topic, func.coalesce(topic_count_subq.c.card_count, 0).label("card_count"))
            .outerjoin(topic_count_subq, topic_count_subq.c.topic_id == Topic.id)
            .where(Topic.id.in_(sem_topic_missing))
        )
        for row in extra_rows:
            t = row.Topic
            topic_map[t.id] = {
                "id": t.id, "name": t.name, "card_count": row.card_count,
                "match_type": "semantic", "score": 0.0,
            }

    # Merge semantic scores; lexical match_type always wins
    for hit in sem_topics:
        tid = hit["topic_id"]
        if tid not in topic_map:
            continue
        entry = topic_map[tid]
        sem_score = 40.0 * hit["similarity"]
        if entry["match_type"] == "semantic":
            entry["score"] = max(entry["score"], sem_score)
        else:
            # Keep lexical match_type; update score only if semantic beats it
            entry["score"] = max(entry["score"], sem_score)

    grouping_topics = sorted(topic_map.values(), key=lambda x: x["score"], reverse=True)[:10]

    # -----------------------------------------------------------------------
    # GROUPINGS — tags
    # -----------------------------------------------------------------------
    tag_count_subq = (
        select(CardTag.tag_id, func.count(CardTag.card_id).label("card_count"))
        .group_by(CardTag.tag_id)
        .subquery()
    )

    lex_tag_rows = await db.execute(
        select(Tag, func.coalesce(tag_count_subq.c.card_count, 0).label("card_count"))
        .outerjoin(tag_count_subq, tag_count_subq.c.tag_id == Tag.id)
        .where(Tag.name.ilike(f"%{q}%"))
    )

    tag_map: dict[int, dict] = {}
    for row in lex_tag_rows:
        t = row.Tag
        s = _name_score(t.name, q_lower)
        if s:
            tag_map[t.id] = {
                "id": t.id, "name": t.name, "card_count": row.card_count,
                "match_type": "lexical", "score": float(s),
            }

    sem_tag_missing = [h["tag_id"] for h in sem_tags if h["tag_id"] not in tag_map]
    if sem_tag_missing:
        extra_rows = await db.execute(
            select(Tag, func.coalesce(tag_count_subq.c.card_count, 0).label("card_count"))
            .outerjoin(tag_count_subq, tag_count_subq.c.tag_id == Tag.id)
            .where(Tag.id.in_(sem_tag_missing))
        )
        for row in extra_rows:
            t = row.Tag
            tag_map[t.id] = {
                "id": t.id, "name": t.name, "card_count": row.card_count,
                "match_type": "semantic", "score": 0.0,
            }

    for hit in sem_tags:
        gid = hit["tag_id"]
        if gid not in tag_map:
            continue
        entry = tag_map[gid]
        sem_score = 40.0 * hit["similarity"]
        entry["score"] = max(entry["score"], sem_score)

    grouping_tags = sorted(tag_map.values(), key=lambda x: x["score"], reverse=True)[:10]

    # -----------------------------------------------------------------------
    # AD-HOC SET + CARDS — hybrid lexical/semantic card matching
    # -----------------------------------------------------------------------

    # Lexical card match (apply optional filters in SQL)
    lex_stmt = select(Card).where(
        or_(
            Card.thai.ilike(f"%{q}%"),
            Card.english.ilike(f"%{q}%"),
            Card.romanization.ilike(f"%{q}%"),
            Card.example_thai.ilike(f"%{q}%"),
        )
    )
    if deck_id is not None:
        lex_stmt = lex_stmt.where(Card.deck_id == deck_id)
    if card_type:
        lex_stmt = lex_stmt.where(Card.card_type == card_type)

    lex_rows = await db.execute(lex_stmt)
    lex_cards = {c.id: c for c in lex_rows.scalars().all()}

    # card_id → {card, score, match_type}
    # Lexical scores: 40–100. Semantic scores for card ranking: 0–30 (strictly below lexical).
    card_hits: dict[int, dict] = {}
    for cid, card in lex_cards.items():
        score, mt = _card_score(card, q_lower)
        if score:
            card_hits[cid] = {"card": card, "score": float(score), "match_type": mt}

    # Semantic card hits — only load cards not already lexically matched, then apply filters
    sem_card_ids_by_sim: dict[int, float] = {h["card_id"]: h["similarity"] for h in sem_cards}
    sem_only_ids = [cid for cid in sem_card_ids_by_sim if cid not in card_hits]

    if sem_only_ids:
        sem_stmt = select(Card).where(Card.id.in_(sem_only_ids))
        if deck_id is not None:
            sem_stmt = sem_stmt.where(Card.deck_id == deck_id)
        if card_type:
            sem_stmt = sem_stmt.where(Card.card_type == card_type)
        sem_rows = await db.execute(sem_stmt)
        for card in sem_rows.scalars().all():
            sim = sem_card_ids_by_sim.get(card.id, 0.0)
            card_hits[card.id] = {
                "card": card,
                "score": round(sim * 30.0, 2),  # capped at 30 — below all lexical scores
                "match_type": "semantic",
            }

    # Sort descending by score; top `cap` form the saveable/studyable set
    sorted_hits = sorted(card_hits.items(), key=lambda x: x[1]["score"], reverse=True)
    total_matched = len(sorted_hits)
    truncated = total_matched > cap
    top_hits = sorted_hits[:cap]
    top_card_ids = [cid for cid, _ in top_hits]

    if not top_card_ids:
        return {
            "query": query,
            "groupings": {"topics": grouping_topics, "tags": grouping_tags},
            "ad_hoc": {
                "card_ids": [],
                "total": 0,
                "topic_spread": [],
                "untagged_count": 0,
                "deck_spread": [],
                "truncated": False,
            },
            "cards": [],
        }

    # Enrich: tags and topics for matched cards
    tag_rows = await db.execute(
        select(CardTag.card_id, Tag.id.label("tag_id"), Tag.name.label("tag_name"))
        .join(Tag, Tag.id == CardTag.tag_id)
        .where(CardTag.card_id.in_(top_card_ids))
    )
    card_tags_map: dict[int, list] = {}
    for row in tag_rows:
        card_tags_map.setdefault(row.card_id, []).append({"id": row.tag_id, "name": row.tag_name})

    topic_rows = await db.execute(
        select(CardTopic.card_id, Topic.id.label("topic_id"), Topic.name.label("topic_name"))
        .join(Topic, Topic.id == CardTopic.topic_id)
        .where(CardTopic.card_id.in_(top_card_ids))
    )
    card_topics_map: dict[int, list] = {}
    for row in topic_rows:
        card_topics_map.setdefault(row.card_id, []).append({"id": row.topic_id, "name": row.topic_name})

    # Build browse cards list
    cards_list = []
    for cid, hit in top_hits:
        card = hit["card"]
        cards_list.append({
            "id": card.id,
            "deck_id": card.deck_id,
            "thai": card.thai,
            "romanization": card.romanization,
            "english": card.english,
            "card_type": card.card_type,
            "tags": card_tags_map.get(card.id, []),
            "topics": card_topics_map.get(card.id, []),
            "score": hit["score"],
            "match_type": hit["match_type"],
        })

    # topic_spread — top 8 topics represented in the matched card set
    topic_spread_rows = await db.execute(
        select(CardTopic.topic_id, Topic.name, func.count(CardTopic.card_id).label("cnt"))
        .join(Topic, Topic.id == CardTopic.topic_id)
        .where(CardTopic.card_id.in_(top_card_ids))
        .group_by(CardTopic.topic_id, Topic.name)
        .order_by(func.count(CardTopic.card_id).desc())
        .limit(8)
    )
    topic_spread = [
        {"topic_id": row.topic_id, "topic_name": row.name, "count": row.cnt}
        for row in topic_spread_rows
    ]

    untagged_count = sum(1 for cid in top_card_ids if not card_topics_map.get(cid))

    # deck_spread — top 8 decks in the matched card set
    deck_spread_rows = await db.execute(
        select(Card.deck_id, Deck.name.label("deck_name"), func.count(Card.id).label("cnt"))
        .join(Deck, Deck.id == Card.deck_id)
        .where(Card.id.in_(top_card_ids))
        .group_by(Card.deck_id, Deck.name)
        .order_by(func.count(Card.id).desc())
        .limit(8)
    )
    deck_spread = [
        {"deck_id": row.deck_id, "deck_name": row.deck_name, "count": row.cnt}
        for row in deck_spread_rows
    ]

    return {
        "query": query,
        "groupings": {"topics": grouping_topics, "tags": grouping_tags},
        "ad_hoc": {
            "card_ids": top_card_ids,
            "total": len(top_card_ids),
            "topic_spread": topic_spread,
            "untagged_count": untagged_count,
            "deck_spread": deck_spread,
            "truncated": truncated,
        },
        "cards": cards_list,
    }
