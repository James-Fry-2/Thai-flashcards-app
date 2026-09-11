"""
Per-user override overlay for card display fields.

Mirrors the resolver pattern in src/utils/romanization.py
(resolve_effective(values, prefs)): a derived value lives on `cards`, a thin
user layer lives elsewhere, and one function decides what's actually shown.
Overrides never mutate `cards` — see the user-flags-overrides design doc for
why (derived columns like compound_breakdown stay freely recomputable by
scripts/backfill_compound_breakdown.py because user corrections don't live
there).

load_overrides(db, card_ids, user_id)  -> dict[int, dict[str, dict]]
    card_id -> {target -> payload}. One batched query.

apply_overrides(card_dict, overrides)  -> dict
    Pure, no I/O. Applies one card's override layer on top of its derived
    dict. Returns the same dict unchanged when there is nothing to apply.

load_open_flag_targets(db, card_ids, user_id) -> dict[int, list[str]]
    card_id -> sorted list of targets with an open flag, for the "has open
    flags" UI marker. One batched query.

upsert_override(db, user_id, card_id, target, payload)
    Shared upsert used by both the /overrides PUT route and the
    resolve-translation route's 'correct' action.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.card_flag import CardFlag
from src.db.models.card_override import CardOverride


async def load_overrides(
    db: AsyncSession, card_ids: list[int], user_id: int
) -> dict[int, dict[str, dict]]:
    """card_id -> {target -> payload}. One query for the whole batch."""
    if not card_ids:
        return {}

    result = await db.execute(
        select(CardOverride).where(
            CardOverride.card_id.in_(card_ids), CardOverride.user_id == user_id
        )
    )
    out: dict[int, dict[str, dict]] = {}
    for row in result.scalars().all():
        try:
            payload = json.loads(row.payload)
        except (ValueError, TypeError):
            continue
        out.setdefault(row.card_id, {})[row.target] = payload
    return out


async def load_open_flag_targets(
    db: AsyncSession, card_ids: list[int], user_id: int
) -> dict[int, list[str]]:
    """card_id -> sorted list of targets with an open flag for this user."""
    if not card_ids:
        return {}

    result = await db.execute(
        select(CardFlag.card_id, CardFlag.target).where(
            CardFlag.card_id.in_(card_ids),
            CardFlag.user_id == user_id,
            CardFlag.status == "open",
        )
    )
    out: dict[int, set[str]] = {}
    for card_id, target in result.all():
        out.setdefault(card_id, set()).add(target)
    return {card_id: sorted(targets) for card_id, targets in out.items()}


def apply_overrides(card_dict: dict, overrides: dict[str, dict]) -> dict:
    """Return card_dict with the user's layer applied. Pure, no I/O.

    - translation -> replaces english, sets english_source="user".
    - compound {suppressed} -> compound_breakdown=None, compound_suppressed=True.
      is_compound is left untouched — it's a structural fact independent of
      display suppression.
    - compound {parts} -> replaces compound_breakdown wholesale, sets
      compound_breakdown_source="user".
    """
    if not overrides:
        return card_dict

    d = dict(card_dict)

    translation = overrides.get("translation")
    if translation and "english" in translation:
        d["english"] = translation["english"]
        d["english_source"] = "user"

    compound = overrides.get("compound")
    if compound:
        if compound.get("suppressed"):
            d["compound_breakdown"] = None
            d["compound_suppressed"] = True
        elif "parts" in compound:
            d["compound_breakdown"] = compound["parts"]
            d["compound_breakdown_source"] = "user"

    return d


async def upsert_override(
    db: AsyncSession, user_id: int, card_id: int, target: str, payload: dict
) -> CardOverride:
    """Upsert the (user_id, card_id, target) override row. Caller commits."""
    existing = await db.scalar(
        select(CardOverride).where(
            CardOverride.user_id == user_id,
            CardOverride.card_id == card_id,
            CardOverride.target == target,
        )
    )
    payload_json = json.dumps(payload, ensure_ascii=False)
    if existing:
        existing.payload = payload_json
        override = existing
    else:
        override = CardOverride(
            user_id=user_id, card_id=card_id, target=target, payload=payload_json
        )
        db.add(override)
    await db.flush()
    return override


async def delete_override(
    db: AsyncSession, user_id: int, card_id: int, target: str
) -> bool:
    """Delete the (user_id, card_id, target) override row if it exists.
    Returns whether a row was deleted. Caller commits."""
    existing = await db.scalar(
        select(CardOverride).where(
            CardOverride.user_id == user_id,
            CardOverride.card_id == card_id,
            CardOverride.target == target,
        )
    )
    if existing is None:
        return False
    await db.delete(existing)
    await db.flush()
    return True
