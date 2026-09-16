"""
The single choke point for every write that changes a card's display value,
files a flag resolution, or moves translation_status from a triage/drawer
decision. `card_override` is the current-state overlay (see
src/utils/card_overrides.py); `card_correction_event` is the append-only
history underneath it, keyed so a correction on one card can later be
offered to other cards carrying the same mistake
(find_propagation_candidates). Nothing here calls the LLM except llm_fill,
which delegates to compound_llm_service.enrich_breakdown() unchanged.

apply_decision(db, user_id, decision, *, source, batch_id=None)
    Validates and applies one decision, appending one event. Caller commits.

undo(db, user_id, *, batch_id=None, event_id=None)
    Reverts one or more prior events (except llm_fill, which is not
    undoable) by restoring prev_override / translation_status / flag state,
    then appends a compensating 'undo' event per reverted event. Returns
    (new_undo_events, skipped_event_ids). Caller commits.

find_propagation_candidates(db, event, user_id)
    Cards (scoped to user_id) with the same normalised Thai as `event` that
    currently show the same wrong value `event` corrected, and have no
    override on that target yet. Suggestions only — never applied
    automatically.
"""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.base import utcnow
from src.db.models.card import Card
from src.db.models.card_flag import CardFlag
from src.db.models.card_correction_event import CardCorrectionEvent
from src.utils.card_overrides import delete_override, load_overrides, upsert_flag, upsert_override
from src.utils.compound import enumerate_segmentations
from src.utils.correction_keys import from_norm as _from_norm, thai_key

_TARGETS = {"translation", "compound", "romanization", "other"}
_SOURCES = {"triage", "drawer"}
_ACTIONS_BY_TARGET = {
    "translation": {"keep", "correct"},
    "compound": {"edit_gloss", "suppress", "llm_fill"},
}
_UNDOABLE_TRANSLATION_STATUS_ACTIONS = {"keep", "correct"}


class CorrectionError(Exception):
    """Invalid decision — route layer maps this to a 422."""


class NoCorrectionApplied:
    """Returned by apply_decision's llm_fill branch instead of an event when
    nothing was actually written to the card — either there were no gaps to
    fill, or enrich_breakdown()'s own confidence guard declined to persist
    the fill. Logging an event (or reporting "enriched") in that case would
    claim a correction happened when cards.compound_breakdown never changed.
    Carries enough of the raw service result for the caller to report an
    honest per-item status without a second call."""

    def __init__(self, status: str, parts: Optional[list] = None):
        self.status = status
        self.parts = parts


def _parse_json(value: Optional[str]):
    if value is None:
        return None
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


def _effective_value(card: Card, target: str, override: Optional[dict]) -> Optional[dict]:
    """The rendered value for `target` as the user currently sees it,
    override applied — mirrors src/utils/card_overrides.py::apply_overrides
    but returns just the one target's value as a plain dict, for snapshotting
    onto an event."""
    if target == "translation":
        english = card.english
        if override and "english" in override:
            english = override["english"]
        return {"english": english}

    if target == "compound":
        parts = _parse_json(card.compound_breakdown) or []
        if override:
            if override.get("suppressed"):
                return {"parts": parts, "suppressed": True}
            if "parts" in override:
                parts = override["parts"]
        return {"parts": parts}

    return None


def _validate_compound_parts(card: Card, parts) -> None:
    if not isinstance(parts, list) or not parts:
        raise CorrectionError("compound decision requires a non-empty 'parts' array in payload")
    thai_sequence = [p.get("thai") if isinstance(p, dict) else None for p in parts]
    if not all(isinstance(t, str) and t for t in thai_sequence):
        raise CorrectionError("every compound part requires a non-empty 'thai' value")
    valid_segmentations = enumerate_segmentations(card.thai, limit=50)
    if thai_sequence not in valid_segmentations:
        raise CorrectionError(
            "parts do not match a valid dictionary segmentation of this card's Thai text"
        )


async def _get_open_flag(db: AsyncSession, user_id: int, card_id: int, target: str) -> Optional[CardFlag]:
    return await db.scalar(
        select(CardFlag).where(
            CardFlag.user_id == user_id,
            CardFlag.card_id == card_id,
            CardFlag.target == target,
            CardFlag.status == "open",
        )
    )


async def validate_decision(db: AsyncSession, decision: dict) -> None:
    """Raise CorrectionError if `decision` is not applyable as-is. Called on
    every decision in a batch before any of them are applied, so an invalid
    item rejects the whole batch without writing anything."""
    target = decision.get("target")
    action = decision.get("action")
    card_id = decision.get("card_id")

    if target not in _TARGETS:
        raise CorrectionError(f"target must be one of {sorted(_TARGETS)}")
    if action == "dismiss_flag":
        pass
    elif action not in _ACTIONS_BY_TARGET.get(target, set()):
        raise CorrectionError(f"action {action!r} is not valid for target {target!r}")

    card = await db.get(Card, card_id) if card_id is not None else None
    if card is None:
        raise CorrectionError(f"card {card_id} not found")

    payload = decision.get("payload") or {}
    if action == "correct":
        english = payload.get("english")
        if not isinstance(english, str) or not english.strip():
            raise CorrectionError("'correct' requires a non-empty 'english' in payload")
    elif action == "edit_gloss":
        _validate_compound_parts(card, payload.get("parts"))


async def apply_decision(
    db: AsyncSession,
    user_id: int,
    decision: dict,
    *,
    source: str,
    batch_id: Optional[str] = None,
):
    """Returns the appended CardCorrectionEvent, or — only for an llm_fill
    decision that turned out to write nothing to the card (no gaps, or a
    fill too low-confidence to persist) — a NoCorrectionApplied sentinel.
    That's the only action for which "nothing happened" is a valid,
    non-error outcome."""
    if source not in _SOURCES:
        raise CorrectionError(f"source must be one of {sorted(_SOURCES)}")

    card_id = decision["card_id"]
    target = decision["target"]
    action = decision["action"]
    payload = decision.get("payload") or {}

    card = await db.get(Card, card_id)
    if card is None:
        raise CorrectionError(f"card {card_id} not found")

    overrides_map = await load_overrides(db, [card_id], user_id)
    current_override = overrides_map.get(card_id, {}).get(target)
    from_value = _effective_value(card, target, current_override)
    prev_override_json = (
        json.dumps(current_override, ensure_ascii=False) if current_override is not None else None
    )

    open_flag = await _get_open_flag(db, user_id, card_id, target)
    to_value: Optional[dict] = None
    llm_tokens: Optional[tuple[int, int]] = None

    if target == "translation" and action == "keep":
        card.translation_status = "confirmed"
        card.translation_candidates = None

    elif target == "translation" and action == "correct":
        english = payload["english"]
        new_payload = {"english": english, "from_candidate": bool(payload.get("from_candidate", False))}
        await upsert_override(db, user_id, card_id, "translation", new_payload)
        card.translation_status = "confirmed"
        card.translation_candidates = None
        to_value = {"english": english}

    elif target == "compound" and action == "edit_gloss":
        parts = payload["parts"]
        _validate_compound_parts(card, parts)
        await upsert_override(db, user_id, card_id, "compound", {"parts": parts})
        to_value = {"parts": parts}

    elif target == "compound" and action == "suppress":
        await upsert_override(db, user_id, card_id, "compound", {"suppressed": True})
        to_value = {"suppressed": True}
        if open_flag is None:
            flagged_value = json.dumps(
                {"compound_breakdown": (from_value or {}).get("parts")}, ensure_ascii=False
            )
            await upsert_flag(
                db, user_id, card_id, "compound",
                "Marked 'not a compound' during triage", flagged_value,
            )
        # Deliberately does not resolve a pre-existing open flag: the
        # rejected split is itself the useful signal this flag exists to
        # carry, whether newly filed here or already open from elsewhere.

    elif target == "compound" and action == "llm_fill":
        from src.db.services import compound_llm_service
        result = await compound_llm_service.enrich_breakdown(db, card_id)
        if result.get("status") in ("no_gaps", "not_compound"):
            # Nothing to log: enrich_breakdown()'s own cost guard already
            # skipped the LLM call, so there's no correction to record.
            return NoCorrectionApplied(result["status"], result.get("parts"))
        if not result.get("persisted"):
            # The LLM did run and proposed a fill, but enrich_breakdown()'s
            # own confidence guard declined to write it to
            # cards.compound_breakdown (see its docstring). Logging an event
            # here would claim a correction that never actually happened —
            # the card row is unchanged, so there's nothing to record.
            return NoCorrectionApplied("low_confidence", result.get("parts"))
        to_value = {"parts": result.get("parts")}
        llm_tokens = (result.get("input_tokens", 0), result.get("output_tokens", 0))

    elif action == "dismiss_flag":
        if open_flag is not None:
            open_flag.status = "dismissed"
            open_flag.resolved_at = utcnow()

    else:
        raise CorrectionError(f"unsupported action {action!r} for target {target!r}")

    # For every content decision except suppress (handled above) and
    # dismiss_flag (already set to 'dismissed', a distinct terminal status),
    # acting on a card resolves whatever open flag was on this target — the
    # decision just made is what that flag was asking for.
    if action not in ("suppress", "dismiss_flag") and open_flag is not None and open_flag.status == "open":
        open_flag.status = "resolved"
        open_flag.resolved_at = utcnow()

    event = CardCorrectionEvent(
        user_id=user_id,
        card_id=card_id,
        thai_key=thai_key(card.thai),
        target=target,
        action=action,
        from_value=json.dumps(from_value, ensure_ascii=False) if from_value is not None else None,
        to_value=json.dumps(to_value, ensure_ascii=False) if to_value is not None else None,
        from_norm=_from_norm(target, from_value),
        prev_override=prev_override_json,
        ai_verdict=decision.get("ai_verdict"),
        ai_reason=decision.get("ai_reason"),
        source=source,
        batch_id=batch_id,
        applied_from_event_id=decision.get("applied_from_event_id"),
    )
    if llm_tokens is not None:
        # Transient, not persisted — lets a batch caller (triage.py) sum
        # tokens across a request without changing this function's uniform
        # return type or duplicating the LLM call to recover them.
        event._llm_tokens = llm_tokens
    db.add(event)
    await db.flush()
    return event


async def _flag_to_reopen(db: AsyncSession, user_id: int, card_id: int, target: str) -> Optional[CardFlag]:
    """The most recently resolved/dismissed flag for (user, card, target).

    The event schema (deliberately, per spec) carries no flag_id column, so
    undo can't point at an exact row — this heuristic (most recent non-open
    row for the tuple) is exactly right for the common case of at most one
    flag in flight per card/target, which is how upsert_flag's own
    refile-in-place behaviour already treats this app's flag lifecycle.
    """
    return await db.scalar(
        select(CardFlag)
        .where(
            CardFlag.user_id == user_id,
            CardFlag.card_id == card_id,
            CardFlag.target == target,
            CardFlag.status != "open",
        )
        .order_by(CardFlag.resolved_at.desc(), CardFlag.id.desc())
    )


async def undo(
    db: AsyncSession,
    user_id: int,
    *,
    batch_id: Optional[str] = None,
    event_id: Optional[int] = None,
) -> tuple[list[CardCorrectionEvent], list[int]]:
    if not batch_id and not event_id:
        raise CorrectionError("undo requires batch_id or event_id")

    stmt = select(CardCorrectionEvent).where(
        CardCorrectionEvent.user_id == user_id,
        CardCorrectionEvent.action != "undo",
    )
    stmt = stmt.where(CardCorrectionEvent.batch_id == batch_id) if batch_id else stmt.where(
        CardCorrectionEvent.id == event_id
    )
    events = list((await db.execute(stmt)).scalars().all())

    new_events: list[CardCorrectionEvent] = []
    skipped: list[int] = []

    for event in events:
        already_reverted = await db.scalar(
            select(CardCorrectionEvent.id).where(CardCorrectionEvent.reverts_event_id == event.id)
        )
        if already_reverted:
            skipped.append(event.id)
            continue
        if event.action == "llm_fill":
            skipped.append(event.id)
            continue

        card = await db.get(Card, event.card_id) if event.card_id else None
        if card is not None:
            if event.target in ("translation", "compound"):
                if event.prev_override:
                    await upsert_override(
                        db, user_id, card.id, event.target, json.loads(event.prev_override)
                    )
                else:
                    await delete_override(db, user_id, card.id, event.target)

            if event.target == "translation" and event.action in _UNDOABLE_TRANSLATION_STATUS_ACTIONS:
                card.translation_status = "flagged"

            flag = await _flag_to_reopen(db, user_id, card.id, event.target)
            if flag is not None:
                flag.status = "open"
                flag.resolved_at = None

        undo_event = CardCorrectionEvent(
            user_id=user_id,
            card_id=event.card_id,
            thai_key=event.thai_key,
            target=event.target,
            action="undo",
            from_value=event.to_value,
            to_value=event.from_value,
            from_norm=None,
            prev_override=None,
            source=event.source,
            batch_id=event.batch_id,
            reverts_event_id=event.id,
        )
        db.add(undo_event)
        await db.flush()
        new_events.append(undo_event)

    return new_events, skipped


async def find_propagation_candidates(
    db: AsyncSession, event: CardCorrectionEvent, user_id: int
) -> list[int]:
    """Card ids (scoped to user_id) that plausibly carry the same mistake
    `event` corrected: same normalised Thai, currently showing the same
    (wrong) value, no override on this target yet. Never applied
    automatically — callers only ever offer these as suggestions."""
    if event.action not in ("correct", "edit_gloss", "suppress", "keep"):
        return []

    target = event.target
    seen_ids: set[int] = {event.card_id} if event.card_id else set()
    candidates: list[Card] = []

    raw_thai = None
    if event.card_id:
        source_card = await db.get(Card, event.card_id)
        if source_card:
            raw_thai = source_card.thai

    if raw_thai is not None:
        result = await db.execute(select(Card).where(Card.thai == raw_thai))
        for c in result.scalars().all():
            if c.id not in seen_ids:
                candidates.append(c)
                seen_ids.add(c.id)

    # Fallback for zero-width/whitespace variants of the same Thai that the
    # equality prefilter above would miss — a full normalised scan, cheap
    # enough at this app's card counts (see design doc).
    all_rows = (await db.execute(select(Card.id, Card.thai))).all()
    for cid, thai in all_rows:
        if cid in seen_ids:
            continue
        try:
            if thai_key(thai) == event.thai_key:
                card = await db.get(Card, cid)
                if card is not None:
                    candidates.append(card)
                    seen_ids.add(cid)
        except ValueError:
            continue

    if not candidates:
        return []

    overrides_map = await load_overrides(db, [c.id for c in candidates], user_id)
    matches: list[int] = []
    for c in candidates:
        if c.id == event.card_id:
            continue
        if overrides_map.get(c.id, {}).get(target) is not None:
            continue
        if event.action == "keep" and c.translation_status != "flagged":
            continue

        effective = _effective_value(c, target, None)
        if _from_norm(target, effective) != event.from_norm:
            continue

        matches.append(c.id)

    return matches
