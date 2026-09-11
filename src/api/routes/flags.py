"""
User-facing content flags (report queue, no correction payload) and the
per-user override overlay (private display-layer corrections that never
mutate `cards`). See the user-flags-overrides design doc for the full
rationale — a flag marks "something here is wrong"; an override changes what
one user sees.

Candidate endpoints (compound-candidates, translation-candidates) are
read-only and computed fresh per request — cheap enough that caching isn't
worth it for how rarely a user opens a correction UI.
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.db.models.base import utcnow
from src.db.models.card import Card
from src.db.models.card_flag import CardFlag
from src.db.services import card_service, lexicon_service
from src.utils.card_overrides import (
    apply_overrides,
    delete_override,
    load_overrides,
    upsert_override,
)
from src.utils.compound import decompose, enumerate_segmentations, gloss_candidates
from src.utils.current_user import current_user

router = APIRouter(tags=["flags"])

_FLAG_TARGETS = {"translation", "compound", "romanization", "example", "other"}
_OVERRIDE_TARGETS = {"translation", "compound"}
_FLAG_STATUSES = {"open", "resolved", "dismissed"}


class FlagCreate(BaseModel):
    target: str
    note: Optional[str] = None


class FlagStatusUpdate(BaseModel):
    status: str


class OverridePut(BaseModel):
    payload: dict


def _parse_json_field(value: Optional[str], default):
    if value is None:
        return default
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def _flag_dict(f: CardFlag) -> dict:
    return {
        "id": f.id,
        "card_id": f.card_id,
        "user_id": f.user_id,
        "target": f.target,
        "note": f.note,
        "flagged_value": _parse_json_field(f.flagged_value, None),
        "status": f.status,
        "created_at": f.created_at.isoformat(),
        "resolved_at": f.resolved_at.isoformat() if f.resolved_at else None,
    }


async def _snapshot_flagged_value(db: AsyncSession, card: Card, target: str, user_id: int) -> Optional[str]:
    """The rendered value for *target* as the user is currently seeing it —
    including any existing override — so a review of this flag months from
    now (after derived data has been recomputed) still shows what the user
    actually looked at."""
    overrides = await load_overrides(db, [card.id], user_id)
    card_overrides = overrides.get(card.id, {})

    if target == "translation":
        d = apply_overrides({"english": card.english}, card_overrides)
        return json.dumps({"english": d["english"]}, ensure_ascii=False)
    if target == "compound":
        base = {"compound_breakdown": _parse_json_field(card.compound_breakdown, None)}
        d = apply_overrides(base, card_overrides)
        return json.dumps({"compound_breakdown": d["compound_breakdown"]}, ensure_ascii=False)
    if target == "romanization":
        return json.dumps({"romanization": card.romanization}, ensure_ascii=False)
    if target == "example":
        return json.dumps(
            {"example_thai": card.example_thai, "example_english": card.example_english},
            ensure_ascii=False,
        )
    return None


async def _validate_override_payload(db: AsyncSession, card: Card, target: str, payload: dict) -> None:
    if target == "translation":
        english = payload.get("english")
        if not isinstance(english, str) or not english.strip():
            raise HTTPException(422, "translation override requires a non-empty 'english' string")
        if "from_candidate" in payload and not isinstance(payload["from_candidate"], bool):
            raise HTTPException(422, "'from_candidate' must be a boolean")
        return

    if target == "compound":
        if payload.get("suppressed") is True:
            return
        parts = payload.get("parts")
        if not isinstance(parts, list) or not parts:
            raise HTTPException(
                422, "compound override requires 'suppressed': true or a non-empty 'parts' array"
            )
        thai_sequence = [p.get("thai") if isinstance(p, dict) else None for p in parts]
        if not all(isinstance(t, str) and t for t in thai_sequence):
            raise HTTPException(422, "every compound part requires a non-empty 'thai' value")
        # The actual guarantee: every part.thai must come from the same
        # dictionary DP that produced the original breakdown, never free
        # text — enforced server-side, not just by the frontend omitting a
        # text box (see "Thai-side rule" in the design doc).
        valid_segmentations = enumerate_segmentations(card.thai, limit=50)
        if thai_sequence not in valid_segmentations:
            raise HTTPException(
                422,
                "parts do not match a valid dictionary segmentation of this card's Thai text",
            )
        return


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

@router.post("/cards/{card_id}/flags", status_code=201)
async def create_flag(card_id: int, payload: FlagCreate, db: AsyncSession = Depends(get_db)):
    if payload.target not in _FLAG_TARGETS:
        raise HTTPException(422, f"target must be one of {sorted(_FLAG_TARGETS)}")

    card = await card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    user_id = current_user()
    flagged_value = await _snapshot_flagged_value(db, card, payload.target, user_id)

    existing = await db.scalar(
        select(CardFlag).where(
            CardFlag.user_id == user_id,
            CardFlag.card_id == card_id,
            CardFlag.target == payload.target,
            CardFlag.status == "open",
        )
    )
    if existing:
        existing.note = payload.note
        existing.flagged_value = flagged_value
        flag = existing
    else:
        flag = CardFlag(
            user_id=user_id,
            card_id=card_id,
            target=payload.target,
            note=payload.note,
            flagged_value=flagged_value,
            status="open",
        )
        db.add(flag)

    await db.flush()
    await db.commit()
    return _flag_dict(flag)


@router.get("/flags")
async def list_flags(
    status: Optional[str] = Query(None),
    target: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    user_id = current_user()
    stmt = select(CardFlag).where(CardFlag.user_id == user_id)
    if status is not None:
        stmt = stmt.where(CardFlag.status == status)
    if target is not None:
        stmt = stmt.where(CardFlag.target == target)
    stmt = stmt.order_by(CardFlag.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(stmt)
    flags = list(result.scalars().all())

    card_ids = [f.card_id for f in flags]
    cards_map: dict[int, Card] = {}
    if card_ids:
        rows = await db.execute(select(Card).where(Card.id.in_(card_ids)))
        cards_map = {c.id: c for c in rows.scalars().all()}

    items = []
    for f in flags:
        card = cards_map.get(f.card_id)
        item = _flag_dict(f)
        item["card"] = (
            {"id": card.id, "thai": card.thai, "english": card.english, "deck_id": card.deck_id}
            if card
            else None
        )
        items.append(item)

    return {"items": items, "limit": limit, "offset": offset}


@router.patch("/flags/{flag_id}")
async def update_flag_status(flag_id: int, payload: FlagStatusUpdate, db: AsyncSession = Depends(get_db)):
    if payload.status not in _FLAG_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(_FLAG_STATUSES)}")

    flag = await db.get(CardFlag, flag_id)
    if not flag:
        raise HTTPException(404, "Flag not found")

    flag.status = payload.status
    flag.resolved_at = utcnow() if payload.status != "open" else None

    await db.flush()
    await db.commit()
    return _flag_dict(flag)


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------

@router.put("/cards/{card_id}/overrides/{target}")
async def upsert_card_override(
    card_id: int, target: str, body: OverridePut, db: AsyncSession = Depends(get_db)
):
    if target not in _OVERRIDE_TARGETS:
        raise HTTPException(422, f"target must be one of {sorted(_OVERRIDE_TARGETS)}")

    card = await card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    await _validate_override_payload(db, card, target, body.payload)

    user_id = current_user()
    await upsert_override(db, user_id, card_id, target, body.payload)
    await db.commit()

    return {"card_id": card_id, "target": target, "payload": body.payload}


@router.delete("/cards/{card_id}/overrides/{target}", status_code=204)
async def delete_card_override(card_id: int, target: str, db: AsyncSession = Depends(get_db)):
    if target not in _OVERRIDE_TARGETS:
        raise HTTPException(422, f"target must be one of {sorted(_OVERRIDE_TARGETS)}")

    user_id = current_user()
    await delete_override(db, user_id, card_id, target)
    await db.commit()


# ---------------------------------------------------------------------------
# Candidate sources
# ---------------------------------------------------------------------------

@router.get("/cards/{card_id}/compound-candidates")
async def get_compound_candidates(card_id: int, db: AsyncSession = Depends(get_db)):
    card = await card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    current_parts = _parse_json_field(card.compound_breakdown, None) or []
    current_thai_sequence = (
        [p["thai"] for p in current_parts] if current_parts else (decompose(card.thai) or [])
    )
    current_gloss_by_part = {p["thai"]: p.get("gloss") for p in current_parts}

    raw_segmentations = enumerate_segmentations(card.thai, limit=8)
    segmentations = [
        {"parts": seg, "is_current": seg == current_thai_sequence} for seg in raw_segmentations
    ]

    part_glosses: dict[str, list[dict]] = {}
    seen_parts: set[str] = set()
    for seg in raw_segmentations:
        for part in seg:
            if part in seen_parts:
                continue
            seen_parts.add(part)
            candidates = await gloss_candidates(db, part)
            current_gloss = current_gloss_by_part.get(part)
            for c in candidates:
                c["is_current"] = current_gloss is not None and c["gloss"] == current_gloss
            part_glosses[part] = candidates

    return {
        "segmentations": segmentations,
        "part_glosses": part_glosses,
        "current": current_parts,
        "allow_free_text_gloss": True,
    }


@router.get("/cards/{card_id}/translation-candidates")
async def get_translation_candidates(card_id: int, db: AsyncSession = Depends(get_db)):
    card = await card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    candidates = await lexicon_service.lookup(db, card.thai)
    return {"candidates": candidates, "allow_free_text": True}
