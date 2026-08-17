"""
Distractor selection for the th_to_en multiple-choice quiz drill mode.

The candidate pool is always the full card library (soft-deleted decks
excluded), regardless of the quiz session's `deck_id`/`topic_id` scope —
scope narrows which cards are *targeted*, never which cards are available as
distractors. See the quiz-mode prompt for the full rationale; do not add a
scope parameter here.
"""
from __future__ import annotations

import random
from typing import Optional

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from src.config.settings import get_settings
from src.db.models.card import Card
from src.db.models.deck import Deck
from src.db.models.card_link import CardLink
from src.db.models.topic import CardTopic
from src.db.services import embedding_service, lexicon_service
from src.utils.text import levenshtein, normalize_gloss, content_words

_ORTHOGRAPHIC_FALLBACK_POOL_CAP = 500
_ORTHOGRAPHIC_FALLBACK_MAX_DISTANCE = 2


def is_valid_distractor(target: Card, candidate: Card) -> tuple[bool, Optional[str]]:
    """Reject candidates that would make a broken (ambiguous or duplicate) item."""
    if candidate.id == target.id:
        return False, "same card"
    if normalize_gloss(candidate.english) == normalize_gloss(target.english):
        return False, "identical gloss"
    if content_words(candidate.english) & content_words(target.english):
        return False, "shared content word"
    if candidate.thai == target.thai:
        return False, "identical thai"
    return True, None


async def _has_lexicon_sense_overlap(db: AsyncSession, target: Card, candidate: Card) -> bool:
    """Reject candidates whose Thai headword's dictionary senses overlap the
    target's, even when the two cards' own chosen glosses look distinct —
    e.g. two different senses picked from words that are dictionary
    near-synonyms. Reuses lexicon_service (translation-check's sense lookup)
    rather than a new lexicon join, per the quiz-mode prompt. Callers already
    reject candidate.thai == target.thai via is_valid_distractor."""
    target_senses = await lexicon_service.lookup(db, target.thai)
    candidate_senses = await lexicon_service.lookup(db, candidate.thai)
    if not target_senses or not candidate_senses:
        return False
    target_words: set[str] = set()
    for s in target_senses:
        target_words |= content_words(s)
    candidate_words: set[str] = set()
    for s in candidate_senses:
        candidate_words |= content_words(s)
    return bool(target_words & candidate_words)


def _active_deck_filter(stmt):
    return stmt.join(Deck, Deck.id == Card.deck_id).where(Deck.deleted_at.is_(None))


async def _confusable_candidates(
    db: AsyncSession, target_id: int, note_filter
) -> list[tuple[Card, Optional[str]]]:
    """card_links is symmetric for 'confusable' (see SYMMETRIC_LINK_TYPES), so
    querying from_card_id alone is sufficient in practice — but a partial
    detection run could leave one-directional rows, so this is not asserted
    here, only in tests."""
    stmt = (
        select(Card, CardLink.note)
        .join(CardLink, CardLink.to_card_id == Card.id)
        .where(
            CardLink.from_card_id == target_id,
            CardLink.link_type == "confusable",
            note_filter,
        )
    )
    stmt = _active_deck_filter(stmt)
    result = await db.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def _deterministic_orthographic_fallback(
    db: AsyncSession, target: Card, exclude_ids: set[int]
) -> Optional[Card]:
    """Cheap on-the-fly orthographic match for when card_links has no
    detected confusable pair for this card yet (detect_confusables.py is a
    batch pass; coverage will be patchy)."""
    stmt = select(Card).where(Card.id.notin_(exclude_ids)).limit(_ORTHOGRAPHIC_FALLBACK_POOL_CAP)
    stmt = _active_deck_filter(stmt)
    result = await db.execute(stmt)
    pool = result.scalars().all()

    if target.syllable_count is None:
        return None

    best: Optional[Card] = None
    best_dist = _ORTHOGRAPHIC_FALLBACK_MAX_DISTANCE + 1
    for candidate in pool:
        if candidate.syllable_count is None:
            continue
        if abs(candidate.syllable_count - target.syllable_count) > 1:
            continue
        dist = levenshtein(target.thai, candidate.thai)
        if dist <= _ORTHOGRAPHIC_FALLBACK_MAX_DISTANCE and dist < best_dist:
            best, best_dist = candidate, dist

    return best


async def _same_topic_candidates(db: AsyncSession, target: Card, exclude_ids: set[int]) -> list[Card]:
    topic_ids_result = await db.execute(
        select(CardTopic.topic_id).where(CardTopic.card_id == target.id)
    )
    topic_ids = [row[0] for row in topic_ids_result.all()]
    if not topic_ids:
        return []
    stmt = (
        select(Card)
        .join(CardTopic, CardTopic.card_id == Card.id)
        .where(CardTopic.topic_id.in_(topic_ids), Card.id.notin_(exclude_ids))
        .distinct()
    )
    stmt = _active_deck_filter(stmt)
    result = await db.execute(stmt)
    candidates = list(result.scalars().all())
    random.shuffle(candidates)
    return candidates


async def _same_type_candidates(db: AsyncSession, target: Card, exclude_ids: set[int]) -> list[Card]:
    stmt = select(Card).where(Card.card_type == target.card_type, Card.id.notin_(exclude_ids))
    stmt = _active_deck_filter(stmt)
    result = await db.execute(stmt)
    candidates = list(result.scalars().all())
    random.shuffle(candidates)
    return candidates


async def _random_candidates(db: AsyncSession, exclude_ids: set[int]) -> list[Card]:
    stmt = select(Card).where(Card.id.notin_(exclude_ids))
    stmt = _active_deck_filter(stmt)
    result = await db.execute(stmt)
    candidates = list(result.scalars().all())
    random.shuffle(candidates)
    return candidates


async def build_option_slate(
    db: AsyncSession,
    target_card_id: int,
    *,
    n_options: int = 4,
) -> list[dict]:
    """Build one th_to_en multiple-choice item's options, target included,
    in randomised order. Regenerated fresh on every call — never cache the
    result per card, or the option set gets trained instead of the word."""
    settings = get_settings()
    target = await db.get(Card, target_card_id)
    if target is None:
        return []

    needed = n_options - 1
    used_ids = {target.id}
    distractors: list[dict] = []
    accepted_cards: list[Card] = []  # validated pairwise below, not just against target

    async def _try_add(candidate: Optional[Card], source: str) -> bool:
        if candidate is None or candidate.id in used_ids or len(distractors) >= needed:
            return False
        # Every option must be valid against the target AND against every
        # other option already accepted into this slate — otherwise two
        # distractors can independently pass the target check while
        # duplicating (or overlapping) each other's gloss.
        for other in [target, *accepted_cards]:
            ok, _reason = is_valid_distractor(other, candidate)
            if not ok:
                return False
            if await _has_lexicon_sense_overlap(db, other, candidate):
                return False
        distractors.append({
            "card_id": candidate.id,
            "english": candidate.english,
            "thai": candidate.thai,
            "source": source,
        })
        accepted_cards.append(candidate)
        used_ids.add(candidate.id)
        return True

    # Slot 1 — orthographic confusable
    ortho_hits = await _confusable_candidates(db, target.id, CardLink.note.ilike("%orthographic%"))
    slot1_filled = False
    for candidate, _note in ortho_hits:
        if await _try_add(candidate, "orthographic"):
            slot1_filled = True
            break

    # Slot 2 — phonetic / tone confusable
    if len(distractors) < needed:
        pt_hits = await _confusable_candidates(
            db, target.id, or_(CardLink.note.ilike("%phonetic%"), CardLink.note.ilike("%tone%"))
        )
        for candidate, note in pt_hits:
            source = "phonetic" if note and "phonetic" in note else "tone"
            if await _try_add(candidate, source):
                break

    # Slot 3 — semantic near-neighbour, banded (not top-k: top-k returns near-synonyms)
    if len(distractors) < needed:
        similar = await embedding_service.find_similar_cards(
            db, target.id, limit=50, min_similarity=settings.distractor_semantic_min
        )
        for hit in similar:
            if len(distractors) >= needed:
                break
            if hit["similarity"] > settings.distractor_semantic_max:
                continue
            candidate = await db.get(Card, hit["card_id"])
            await _try_add(candidate, "semantic")

    # Deterministic orthographic fallback — only if slot 1 found nothing
    if not slot1_filled and len(distractors) < needed:
        fallback = await _deterministic_orthographic_fallback(db, target, used_ids)
        await _try_add(fallback, "orthographic")

    # Backfill ladder: same topic -> same card_type -> random
    if len(distractors) < needed:
        for candidate in await _same_topic_candidates(db, target, used_ids):
            if len(distractors) >= needed:
                break
            await _try_add(candidate, "topic")

    if len(distractors) < needed:
        for candidate in await _same_type_candidates(db, target, used_ids):
            if len(distractors) >= needed:
                break
            await _try_add(candidate, "same_type")

    if len(distractors) < needed:
        for candidate in await _random_candidates(db, used_ids):
            if len(distractors) >= needed:
                break
            await _try_add(candidate, "random")

    if len(distractors) < needed:
        logger.warning(
            f"quiz distractor pool too thin for card {target.id}: "
            f"only {len(distractors)}/{needed} valid distractors found"
        )

    slate = [{
        "card_id": target.id,
        "english": target.english,
        "thai": target.thai,
        "source": "target",
    }] + distractors

    random.shuffle(slate)
    for i, option in enumerate(slate):
        option["position"] = i

    return slate
