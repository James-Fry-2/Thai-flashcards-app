import json
import numpy as np
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.card import Card
from src.db.models.card_link import CardLink, LINK_TYPES
from src.db.models.embeddings import CardEmbedding
from src.db.models.tag import CardTag, Tag
from src.llm.registry import get_provider, LLMTask
from src.llm.prompts.link_suggestion import build_link_suggestion_messages
from src.utils.embeddings import cosine_similarity_matrix


async def suggest_links(
    db: AsyncSession,
    card_id: int,
    max_candidates: int = 50,
) -> list[dict]:
    """
    Use Claude to suggest semantically related cards for a given card.

    Strategy:
    1. Load the target card and its tags.
    2. Fetch candidates: cards sharing ≥1 tag with the target, or same card_type in
       the same deck. Exclude the card itself and already-linked cards.
    3. Cap at max_candidates to control token usage.
    4. Call Claude and parse the JSON response.
    5. Return validated suggestions (confidence >= 0.6, link_type in LINK_TYPES).
    """
    card = await db.get(Card, card_id)
    if not card:
        return []

    # Load current tags for the target card
    tag_result = await db.execute(
        select(Tag.name)
        .join(CardTag, CardTag.tag_id == Tag.id)
        .where(CardTag.card_id == card_id)
    )
    tags = [row[0] for row in tag_result]

    # Find already-linked card ids (both directions) to exclude
    linked_result = await db.execute(
        select(CardLink.from_card_id, CardLink.to_card_id).where(
            (CardLink.from_card_id == card_id) | (CardLink.to_card_id == card_id)
        )
    )
    linked_ids: set[int] = {card_id}
    for row in linked_result:
        linked_ids.add(row.from_card_id)
        linked_ids.add(row.to_card_id)

    # Step 1: tag-sharing candidates (fast path once tags exist)
    tag_candidate_stmt = (
        select(Card)
        .join(CardTag, CardTag.card_id == Card.id)
        .where(
            CardTag.tag_id.in_(
                select(CardTag.tag_id).where(CardTag.card_id == card_id)
            ),
            Card.id.notin_(list(linked_ids)),
        )
        .distinct()
    )
    tag_result = await db.execute(tag_candidate_stmt)
    tag_candidates = list(tag_result.scalars().all())

    # Step 2: fetch ALL remaining cards across all decks, bigram-rank them,
    # then take the top N to fill the budget.
    existing_ids = linked_ids | {c.id for c in tag_candidates}
    all_cards_result = await db.execute(
        select(Card).where(Card.id.notin_(list(existing_ids)))
    )
    deck_cards = list(all_cards_result.scalars().all())
    budget = max_candidates - len(tag_candidates)
    ranked_deck = await _rank_candidates(db, card_id, deck_cards, budget)

    candidates = tag_candidates + ranked_deck

    if not candidates:
        return []

    candidate_dicts = [
        {"id": c.id, "thai": c.thai, "english": c.english, "card_type": c.card_type}
        for c in candidates
    ]

    messages = build_link_suggestion_messages(
        thai=card.thai,
        english=card.english,
        card_type=card.card_type,
        tags=tags,
        candidates=candidate_dicts,
    )

    provider = get_provider(LLMTask.LINK_SUGGESTION)
    response = await provider.complete(messages)

    return _parse_suggestions(response.text, valid_card_ids={c.id for c in candidates})


async def _rank_candidates(
    db: AsyncSession,
    target_card_id: int,
    candidates: list[Card],
    limit: int,
) -> list[Card]:
    """
    Rank candidates by embedding similarity to the target card.
    Falls back to bigram ranking if embeddings are unavailable for the target or all candidates.
    """
    if not candidates:
        return []

    target_emb = await db.get(CardEmbedding, target_card_id)
    if target_emb is None:
        logger.info(
            f"link_suggestion: card {target_card_id} has no embedding, falling back to bigram ranking"
        )
        target_card = await db.get(Card, target_card_id)
        return _rank_candidates_bigram(
            target_card.thai if target_card else "", candidates, limit
        )

    candidate_ids = [c.id for c in candidates]
    emb_result = await db.execute(
        select(CardEmbedding).where(CardEmbedding.card_id.in_(candidate_ids))
    )
    emb_map: dict[int, bytes] = {e.card_id: e.embedding for e in emb_result.scalars().all()}

    if not emb_map:
        logger.info(
            f"link_suggestion: no candidate embeddings found for card {target_card_id}, "
            "falling back to bigram ranking"
        )
        target_card = await db.get(Card, target_card_id)
        return _rank_candidates_bigram(
            target_card.thai if target_card else "", candidates, limit
        )

    query_vec = np.frombuffer(target_emb.embedding, dtype=np.float32).tolist()
    cards_with_emb = [(c, emb_map[c.id]) for c in candidates if c.id in emb_map]
    cards_without_emb = [c for c in candidates if c.id not in emb_map]

    corpus = [np.frombuffer(blob, dtype=np.float32).tolist() for _, blob in cards_with_emb]
    sims = cosine_similarity_matrix(query_vec, corpus)

    scored = sorted(
        zip(sims, [c for c, _ in cards_with_emb]),
        key=lambda x: x[0],
        reverse=True,
    )
    # Cards without embeddings go at the end (better than nothing)
    ranked = [c for _, c in scored] + cards_without_emb
    return ranked[:limit]


def _rank_candidates_bigram(target_thai: str, candidates: list[Card], limit: int) -> list[Card]:
    """
    Sort candidates by descending Thai-substring overlap with the target.
    Thai is written without spaces, so we score by shared character bigrams.
    """
    def bigrams(text: str) -> set[str]:
        return {text[i:i+2] for i in range(len(text) - 1)}

    target_bg = bigrams(target_thai)

    def score(card: Card) -> int:
        return len(target_bg & bigrams(card.thai))

    return sorted(candidates, key=score, reverse=True)[:limit]


def _parse_suggestions(raw: str, valid_card_ids: set[int]) -> list[dict]:
    """Parse and validate Claude's JSON response."""
    try:
        from json_repair import repair_json
        data = json.loads(repair_json(raw.strip()))
    except (json.JSONDecodeError, Exception):
        return []

    if not isinstance(data, list):
        return []

    results = []
    seen_ids: set[int] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        card_id = item.get("card_id")
        link_type = item.get("link_type")
        confidence = item.get("confidence")
        reason = item.get("reason", "")

        if not isinstance(card_id, int):
            continue
        if card_id not in valid_card_ids:
            continue
        if card_id in seen_ids:
            continue
        if link_type not in LINK_TYPES:
            continue
        if not isinstance(confidence, (int, float)) or confidence < 0.6:
            continue

        seen_ids.add(card_id)
        results.append({
            "card_id": card_id,
            "link_type": link_type,
            "confidence": round(float(confidence), 3),
            "reason": str(reason),
        })

    return results
