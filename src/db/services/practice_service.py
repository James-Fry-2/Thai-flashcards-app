"""
Practice-session builder: interleaves exercise types (from the registry in
src/practice/registry.py) over a scoped set of cards. FSRS-free — writes
nothing here, callers persist the session/attempts separately (see
src/api/routes/practice.py).
"""
from __future__ import annotations

import json
import random
from typing import Optional

from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.card import Card
from src.db.models.deck import Deck
from src.db.models.topic import CardTopic
from src.practice.registry import REGISTRY, ExerciseType


def _parse_json(v: Optional[str]):
    if v is None:
        return None
    try:
        return json.loads(v)
    except Exception:
        return None


async def _select_target_cards(
    db: AsyncSession, scope_type: str, scope_id: Optional[int], limit: int
) -> list[Card]:
    """Target selection only — scope narrows which cards are practiced,
    never the distractor candidate pool (that's always the full library;
    see distractor_service). Randomised in SQL so the candidate pool is
    drawn from the whole scope, not just the lowest card ids."""
    stmt = select(Card).join(Deck, Deck.id == Card.deck_id).where(Deck.deleted_at.is_(None))
    if scope_type == "deck" and scope_id is not None:
        stmt = stmt.where(Card.deck_id == scope_id)
    elif scope_type == "topic" and scope_id is not None:
        stmt = stmt.join(CardTopic, CardTopic.card_id == Card.id).where(CardTopic.topic_id == scope_id)
    # Over-fetch: some targets will be skipped when no eligible exercise
    # produces a payload.
    stmt = stmt.order_by(func.random()).limit(limit * 3)
    result = await db.execute(stmt)
    return list(result.scalars().all())


def _build_item(card: Card, exercise: ExerciseType, payload: dict) -> dict:
    item = {
        "card_id": card.id,
        "exercise_type": exercise.key,
        "grading": exercise.grading,
        "thai": card.thai,
        "romanization": card.romanization,
        "payload": payload,
    }
    if exercise.grading == "self_rated":
        # The back face is the answer for a binary exercise — only attach
        # it for self-rated exercises, where the client needs it to render
        # the flip (e.g. recall_th_en reusing FlashCard).
        item["english"] = card.english
        item["example_thai"] = card.example_thai
        item["example_english"] = card.example_english
        item["compound_breakdown"] = _parse_json(card.compound_breakdown)
    return item


async def build_session(
    db: AsyncSession,
    *,
    scope_type: str,
    scope_id: Optional[int],
    limit: int,
    exercise_types: Optional[list[str]] = None,
) -> list[dict]:
    """Returns a list of practice items, target cards deduplicated, exercise
    types interleaved. `exercise_types=None` means every registered type is
    eligible for assignment; a restricted list (e.g. ["mc_th_en"] for the
    /quiz shim) narrows the registry, not the candidate pool."""
    allowed_keys = exercise_types if exercise_types is not None else list(REGISTRY.keys())
    allowed = [REGISTRY[k] for k in allowed_keys if k in REGISTRY]
    if not allowed:
        return []

    candidates = await _select_target_cards(db, scope_type, scope_id, limit)

    items: list[dict] = []
    for card in candidates:
        if len(items) >= limit:
            break

        eligible = [ex for ex in allowed if ex.is_eligible(card)]
        # Uniform-random assignment among eligible types — not familiarity
        # driven (see decision 2 in the practice-mode prompt). NOTE: a card
        # with a too-thin distractor pool falls back to whatever exercise
        # tries next (e.g. recall) rather than being dropped — a mild,
        # accepted bias for v1 (assignment isn't perfectly uniform for those
        # cards). Must be controlled for in any later per-exercise
        # difficulty analysis.
        random.shuffle(eligible)

        item = None
        for exercise in eligible:
            payload = await exercise.build_payload(db, card)
            if payload is None:
                continue
            item = _build_item(card, exercise, payload)
            break

        if item is None:
            logger.warning(f"practice: no eligible exercise produced a payload for card {card.id}")
            continue

        items.append(item)

    random.shuffle(items)  # interleave exercise types
    return items
