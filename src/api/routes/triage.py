"""
Card triage: a dedicated screen for clearing flagged translations, compound
gloss gaps, and open user flags in one sitting, plus "apply to matching
cards" suggestions fed by the correction-event history
(src/db/services/correction_service.py). Separate from review — nothing
here touches CardSchedule, ReviewLog, review sessions, or FSRS, same
isolation as the MC quiz / practice-mode pass.

Every write here goes through correction_service.apply_decision(), the same
choke point the drawer's override/resolve-translation routes were rerouted
through in flags.py / cards.py. This module only orchestrates: building the
queue, running batch AI checks, and applying/undoing decisions.
"""
import asyncio
import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.db.database import get_session_factory
from src.db.models.card import Card
from src.db.models.card_flag import CardFlag
from src.db.models.card_correction_event import CardCorrectionEvent
from src.db.models.upload import Upload
from src.db.services import correction_service, translation_verify_service
from src.db.services.compound_llm_service import _current_parts as _compound_current_parts
from src.utils.card_overrides import load_overrides
from src.utils.correction_keys import thai_key
from src.utils.current_user import current_user

router = APIRouter(tags=["triage"])

_MAX_BATCH = 50
_PROPAGATION_ACTIONS = ("correct", "edit_gloss", "suppress", "keep")


def _parse_json(value: Optional[str], default=None):
    if value is None:
        return default
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


class CardIdsRequest(BaseModel):
    card_ids: list[int]


class DecisionIn(BaseModel):
    card_id: int
    target: str
    action: str
    payload: Optional[dict] = None
    ai_verdict: Optional[str] = None
    ai_reason: Optional[str] = None
    applied_from_event_id: Optional[int] = None


class DecisionsRequest(BaseModel):
    decisions: list[DecisionIn]


class UndoRequest(BaseModel):
    batch_id: Optional[str] = None
    event_id: Optional[int] = None


def _check_batch_size(card_ids: list[int]) -> None:
    if len(card_ids) > _MAX_BATCH:
        raise HTTPException(422, f"card_ids: max {_MAX_BATCH} per batch")


# ---------------------------------------------------------------------------
# GET /triage/queue
# ---------------------------------------------------------------------------

async def _translation_group(db: AsyncSession, user_id: int) -> list[dict]:
    cards = list((
        await db.execute(select(Card).where(Card.translation_status == "flagged"))
    ).scalars().all())
    if not cards:
        return []

    overrides_map = await load_overrides(db, [c.id for c in cards], user_id)
    cards = [c for c in cards if "translation" not in overrides_map.get(c.id, {})]
    if not cards:
        return []

    upload_ids = [c.source_upload_id for c in cards if c.source_upload_id]
    uploads_map: dict[int, Upload] = {}
    if upload_ids:
        rows = await db.execute(select(Upload).where(Upload.id.in_(upload_ids)))
        uploads_map = {u.id: u for u in rows.scalars().all()}

    items = []
    for c in cards:
        upload = uploads_map.get(c.source_upload_id) if c.source_upload_id else None
        items.append({
            "card_id": c.id,
            "thai": c.thai,
            "romanization": c.romanization,
            "english": c.english,
            "translation_candidates": _parse_json(c.translation_candidates, []),
            "source_title": upload.source_title if upload else None,
            "chapter_label": upload.chapter_label if upload else None,
        })
    return items


async def _compound_gap_group(db: AsyncSession, user_id: int) -> list[dict]:
    cards = list((
        await db.execute(select(Card).where(Card.is_compound.is_(True)))
    ).scalars().all())
    if not cards:
        return []

    overrides_map = await load_overrides(db, [c.id for c in cards], user_id)

    items = []
    for c in cards:
        override = overrides_map.get(c.id, {}).get("compound")
        if override and override.get("suppressed"):
            continue

        if override and "parts" in override:
            parts = override["parts"]
        else:
            parts = await _compound_current_parts(db, c)

        if not parts:
            continue

        missing = [p for p in parts if not p.get("gloss")]
        if not missing:
            continue

        items.append({
            "card_id": c.id,
            "thai": c.thai,
            "english": c.english,
            "parts": parts,
            "missing_parts": [p.get("thai") for p in missing],
        })
    return items


async def _open_flags_group(
    db: AsyncSession, user_id: int, translation_ids: set[int], compound_gap_ids: set[int]
) -> list[dict]:
    rows = list((
        await db.execute(
            select(CardFlag).where(CardFlag.user_id == user_id, CardFlag.status == "open")
        )
    ).scalars().all())

    rows = [
        f for f in rows
        if not (f.target == "translation" and f.card_id in translation_ids)
        and not (f.target == "compound" and f.card_id in compound_gap_ids)
    ]
    if not rows:
        return []

    card_ids = [f.card_id for f in rows]
    cards_map = {c.id: c for c in (await db.execute(select(Card).where(Card.id.in_(card_ids)))).scalars().all()}

    items = []
    for f in rows:
        card = cards_map.get(f.card_id)
        items.append({
            "flag_id": f.id,
            "card_id": f.card_id,
            "target": f.target,
            "note": f.note,
            "flagged_value": _parse_json(f.flagged_value),
            "card": {"id": card.id, "thai": card.thai, "english": card.english} if card else None,
        })
    return items


async def _recent_propagatable_events(db: AsyncSession, user_id: int, limit: int = 50) -> list[CardCorrectionEvent]:
    reverted_subq = select(CardCorrectionEvent.reverts_event_id).where(
        CardCorrectionEvent.user_id == user_id,
        CardCorrectionEvent.reverts_event_id.is_not(None),
    )
    stmt = (
        select(CardCorrectionEvent)
        .where(
            CardCorrectionEvent.user_id == user_id,
            CardCorrectionEvent.action.in_(_PROPAGATION_ACTIONS),
            CardCorrectionEvent.id.not_in(reverted_subq),
        )
        .order_by(CardCorrectionEvent.created_at.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def _suggested_group(db: AsyncSession, user_id: int) -> list[dict]:
    events = await _recent_propagatable_events(db, user_id)
    if not events:
        return []

    seen_pairs: set[tuple[int, str]] = set()
    raw_items: list[dict] = []
    for event in events:
        candidate_ids = await correction_service.find_propagation_candidates(db, event, user_id)
        for cid in candidate_ids:
            key = (cid, event.target)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            raw_items.append({
                "card_id": cid,
                "target": event.target,
                "event_id": event.id,
                "from_value": _parse_json(event.from_value),
                "to_value": _parse_json(event.to_value),
            })

    if not raw_items:
        return []

    card_ids = [it["card_id"] for it in raw_items]
    cards_map = {c.id: c for c in (await db.execute(select(Card).where(Card.id.in_(card_ids)))).scalars().all()}

    items = []
    for it in raw_items:
        card = cards_map.get(it["card_id"])
        if card is None:
            continue
        it["card"] = {"id": card.id, "thai": card.thai, "english": card.english}
        items.append(it)
    return items


@router.get("/triage/queue")
async def get_triage_queue(db: AsyncSession = Depends(get_db)):
    user_id = current_user()

    translation = await _translation_group(db, user_id)
    compound_gap = await _compound_gap_group(db, user_id)
    open_flags = await _open_flags_group(
        db, user_id,
        translation_ids={it["card_id"] for it in translation},
        compound_gap_ids={it["card_id"] for it in compound_gap},
    )
    suggested = await _suggested_group(db, user_id)

    return {
        "groups": {
            "translation": translation,
            "compound_gap": compound_gap,
            "open_flags": open_flags,
            "suggested": suggested,
        },
        "counts": {
            "translation": len(translation),
            "compound_gap": len(compound_gap),
            "open_flags": len(open_flags),
            "suggested": len(suggested),
        },
    }


# ---------------------------------------------------------------------------
# POST /triage/verify-translations
# ---------------------------------------------------------------------------

@router.post("/triage/verify-translations")
async def verify_translations_batch(payload: CardIdsRequest):
    """Runs verify_translation() per card, up to 4 at a time. Each task
    opens its own DB session — sharing one AsyncSession across concurrent
    coroutines is unsafe, and these calls are network-bound (the LLM call),
    so real concurrency is the point of the semaphore."""
    _check_batch_size(payload.card_ids)

    factory = get_session_factory()
    sem = asyncio.Semaphore(4)
    items: list[Optional[dict]] = [None] * len(payload.card_ids)
    tokens = {"in": 0, "out": 0}

    async def _one(i: int, card_id: int) -> None:
        async with sem:
            try:
                async with factory() as session:
                    result = await translation_verify_service.verify_translation(session, card_id)
            except Exception as exc:
                items[i] = {"card_id": card_id, "status": "error", "error": str(exc)}
                return
            tokens["in"] += result.get("input_tokens", 0)
            tokens["out"] += result.get("output_tokens", 0)
            items[i] = {
                "card_id": card_id,
                "status": result.get("status"),
                "verdict": result.get("verdict"),
                "reason": result.get("reason"),
            }

    await asyncio.gather(*[_one(i, cid) for i, cid in enumerate(payload.card_ids)])

    logger.info(
        f"triage.verify_translations_batch: cards={len(payload.card_ids)} "
        f"input_tokens={tokens['in']} output_tokens={tokens['out']}"
    )
    return {"items": items}


# ---------------------------------------------------------------------------
# POST /triage/enrich-breakdowns
# ---------------------------------------------------------------------------

@router.post("/triage/enrich-breakdowns")
async def enrich_breakdowns_batch(payload: CardIdsRequest):
    """Each item is routed through correction_service.apply_decision() so
    it's logged — same isolated-session-per-task reasoning as
    verify_translations_batch above. A card with nothing to fill ('no_gaps'/
    'not_compound') or a fill too low-confidence to persist
    ('low_confidence') gets a NoCorrectionApplied sentinel back instead of
    an event — no event is written, since the card wasn't actually
    changed."""
    _check_batch_size(payload.card_ids)

    factory = get_session_factory()
    sem = asyncio.Semaphore(4)
    items: list[Optional[dict]] = [None] * len(payload.card_ids)
    tokens = {"in": 0, "out": 0}
    user_id = current_user()

    async def _one(i: int, card_id: int) -> None:
        async with sem:
            try:
                async with factory() as session:
                    event = await correction_service.apply_decision(
                        session, user_id,
                        {"card_id": card_id, "target": "compound", "action": "llm_fill"},
                        source="triage",
                    )
                    await session.commit()
            except correction_service.CorrectionError as exc:
                items[i] = {"card_id": card_id, "status": "error", "error": str(exc)}
                return
            except Exception as exc:
                items[i] = {"card_id": card_id, "status": "error", "error": str(exc)}
                return

            if isinstance(event, correction_service.NoCorrectionApplied):
                items[i] = {"card_id": card_id, "status": event.status, "parts": event.parts}
                return

            tin, tout = getattr(event, "_llm_tokens", (0, 0))
            tokens["in"] += tin
            tokens["out"] += tout
            to_value = _parse_json(event.to_value, {})
            items[i] = {
                "card_id": card_id,
                "status": "enriched",
                "event_id": event.id,
                "parts": to_value.get("parts"),
            }

    await asyncio.gather(*[_one(i, cid) for i, cid in enumerate(payload.card_ids)])

    logger.info(
        f"triage.enrich_breakdowns_batch: cards={len(payload.card_ids)} "
        f"input_tokens={tokens['in']} output_tokens={tokens['out']}"
    )
    return {"items": items}


# ---------------------------------------------------------------------------
# POST /triage/decisions
# ---------------------------------------------------------------------------

@router.post("/triage/decisions")
async def submit_decisions(payload: DecisionsRequest, db: AsyncSession = Depends(get_db)):
    if not payload.decisions:
        raise HTTPException(422, "decisions must be a non-empty array")

    user_id = current_user()
    decisions = [d.model_dump(exclude_none=True) for d in payload.decisions]

    for d in decisions:
        try:
            await correction_service.validate_decision(db, d)
        except correction_service.CorrectionError as exc:
            raise HTTPException(422, str(exc)) from exc

    batch_id = str(uuid.uuid4()) if len(decisions) > 1 else None

    events = []
    for d in decisions:
        event = await correction_service.apply_decision(db, user_id, d, source="triage", batch_id=batch_id)
        if event is not None:
            events.append(event)

    await db.commit()

    results = []
    for event in events:
        candidate_ids = await correction_service.find_propagation_candidates(db, event, user_id)
        results.append({
            "event_id": event.id,
            "card_id": event.card_id,
            "propagation_candidates": candidate_ids,
        })

    return {"batch_id": batch_id, "events": results}


# ---------------------------------------------------------------------------
# POST /triage/undo
# ---------------------------------------------------------------------------

@router.post("/triage/undo")
async def undo_decisions(payload: UndoRequest, db: AsyncSession = Depends(get_db)):
    if not payload.batch_id and not payload.event_id:
        raise HTTPException(422, "batch_id or event_id is required")

    user_id = current_user()
    try:
        new_events, skipped = await correction_service.undo(
            db, user_id, batch_id=payload.batch_id, event_id=payload.event_id
        )
    except correction_service.CorrectionError as exc:
        raise HTTPException(422, str(exc)) from exc

    await db.commit()

    return {
        "reverted": [e.reverts_event_id for e in new_events],
        "skipped": skipped,
    }


# ---------------------------------------------------------------------------
# GET /corrections
# ---------------------------------------------------------------------------

def _event_dict(e: CardCorrectionEvent) -> dict:
    return {
        "id": e.id,
        "card_id": e.card_id,
        "thai_key": e.thai_key,
        "target": e.target,
        "action": e.action,
        "from_value": _parse_json(e.from_value),
        "to_value": _parse_json(e.to_value),
        "ai_verdict": e.ai_verdict,
        "ai_reason": e.ai_reason,
        "source": e.source,
        "batch_id": e.batch_id,
        "applied_from_event_id": e.applied_from_event_id,
        "reverts_event_id": e.reverts_event_id,
        "created_at": e.created_at.isoformat(),
    }


@router.get("/corrections")
async def list_corrections(
    card_id: Optional[int] = Query(None),
    thai: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    user_id = current_user()
    stmt = select(CardCorrectionEvent).where(CardCorrectionEvent.user_id == user_id)
    if card_id is not None:
        stmt = stmt.where(CardCorrectionEvent.card_id == card_id)
    if thai is not None:
        stmt = stmt.where(CardCorrectionEvent.thai_key == thai_key(thai))
    stmt = stmt.order_by(CardCorrectionEvent.created_at.desc()).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_event_dict(e) for e in rows]}
