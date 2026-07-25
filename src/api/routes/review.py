from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from src.api.deps import get_db
from src.db.services import card_service, review_service, gamification_service
from src.db.services import review_session_service
from src.db.models.card import Card
from src.db.models.card_schedule import CardSchedule
from src.db.models.review_log import ReviewLog
from src.db.models.review_session import ReviewSession

router = APIRouter(prefix="/review", tags=["review"])


class RateRequest(BaseModel):
    card_id: int
    schedule_id: int
    rating: int  # 1=Again 2=Hard 3=Good 4=Easy


class FromCardsRequest(BaseModel):
    card_ids: list[int]
    direction: str = "th_to_en"


def _build_card_payload(c: Card, s: CardSchedule) -> dict:
    import json as _json

    def _parse(v):
        if v is None:
            return None
        try:
            return _json.loads(v)
        except Exception:
            return None

    return {
        "id": c.id,
        "card_id": c.id,
        "schedule_id": s.id,
        "thai": c.thai,
        "romanization": c.romanization,
        "english": c.english,
        "example_thai": c.example_thai,
        "example_english": c.example_english,
        "card_type": c.card_type,
        "fsrs_state": s.fsrs_state,
        "is_compound": c.is_compound,
        "compound_breakdown": _parse(c.compound_breakdown),
    }


def _interleave_mixed(
    due_pairs: list[tuple[Card, CardSchedule]],
    atrisk_pairs: list[tuple[Card, CardSchedule]],
    limit: int,
) -> list[tuple[Card, CardSchedule]]:
    """Deterministic interleave: slots where slot%5 >= 3 take from at-risk (40%), rest from due.
    Falls back to the other bucket when one is exhausted. Deduplicates by card id."""
    due_ids = {c.id for c, _ in due_pairs}
    atrisk_deduped = [(c, s) for c, s in atrisk_pairs if c.id not in due_ids]

    result: list[tuple[Card, CardSchedule]] = []
    d_i = a_i = slot = 0

    while len(result) < limit and (d_i < len(due_pairs) or a_i < len(atrisk_deduped)):
        prefer_atrisk = (slot % 5) >= 3

        if prefer_atrisk and a_i < len(atrisk_deduped):
            result.append(atrisk_deduped[a_i]); a_i += 1
        elif not prefer_atrisk and d_i < len(due_pairs):
            result.append(due_pairs[d_i]); d_i += 1
        elif d_i < len(due_pairs):
            result.append(due_pairs[d_i]); d_i += 1
        elif a_i < len(atrisk_deduped):
            result.append(atrisk_deduped[a_i]); a_i += 1
        else:
            break
        slot += 1

    return result


@router.get("/summary")
async def get_due_summary(db: AsyncSession = Depends(get_db)):
    """Library-wide due/new card counts and top-5 breakdown by deck and topic."""
    return await card_service.get_due_summary(db)


@router.post("/session")
async def start_session(
    deck_id: Optional[int] = Query(None),
    topic_id: Optional[int] = Query(None),
    upload_id: Optional[int] = Query(None),
    scope: Optional[str] = Query(None),
    strategy: str = Query("due"),
    direction: str = Query("th_to_en"),
    db: AsyncSession = Depends(get_db),
):
    scope_count = sum([
        deck_id is not None,
        topic_id is not None,
        upload_id is not None,
        scope == "library",
    ])
    if scope_count != 1:
        raise HTTPException(
            422,
            "Provide exactly one of: deck_id=N, topic_id=N, upload_id=N, or scope=library",
        )

    # Mark any sessions left open longer than 24h as abandoned (housekeeping on natural traffic).
    await review_session_service.abandon_stale_sessions(db)

    if deck_id is not None:
        card_schedule_pairs = await card_service.get_due_cards(db, deck_id, limit=20, direction=direction)
        session_scope, scope_id, session_strategy = "deck", deck_id, None

    elif topic_id is not None:
        card_schedule_pairs = await card_service.get_due_cards_for_topic(db, topic_id, limit=20, direction=direction)
        session_scope, scope_id, session_strategy = "topic", topic_id, None

    elif upload_id is not None:
        card_schedule_pairs = await card_service.get_due_cards_for_upload(
            db, upload_id, limit=200, direction=direction
        )
        session_scope, scope_id, session_strategy = "upload", upload_id, None

    else:  # scope == "library"
        if strategy not in ("due", "at_risk", "mixed"):
            raise HTTPException(422, f"Unknown strategy {strategy!r}. Use: due, at_risk, mixed")

        session_scope, scope_id, session_strategy = "library", None, strategy

        if strategy == "due":
            card_schedule_pairs = await card_service.get_due_cards_library_wide(
                db, limit=50, direction=direction
            )
        elif strategy == "at_risk":
            card_schedule_pairs = await card_service.get_at_risk_card_pairs(
                db, limit=20, direction=direction
            )
        else:  # mixed
            due_pairs = await card_service.get_due_cards_library_wide(
                db, limit=50, direction=direction
            )
            atrisk_pairs = await card_service.get_at_risk_card_pairs(
                db, limit=20, direction=direction
            )
            card_schedule_pairs = _interleave_mixed(due_pairs, atrisk_pairs, limit=50)

    db_session = await review_session_service.create_session(
        db, session_scope, scope_id, session_strategy, direction
    )
    await db.commit()
    await db.refresh(db_session)

    cards = [_build_card_payload(c, s) for c, s in card_schedule_pairs]

    return {"session_id": db_session.id, "total_cards": len(cards), "cards": cards}


@router.post("/session/from-cards")
async def start_session_from_cards(
    payload: FromCardsRequest,
    db: AsyncSession = Depends(get_db),
):
    """Start a session from an explicit list of card IDs (e.g. at-risk filtered list)."""
    if not payload.card_ids:
        raise HTTPException(422, "card_ids must not be empty")
    if len(payload.card_ids) > 500:
        raise HTTPException(422, "card_ids must contain at most 500 items")

    await review_session_service.abandon_stale_sessions(db)

    rows = await db.execute(
        select(Card, CardSchedule)
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(
            Card.id.in_(payload.card_ids),
            CardSchedule.direction == payload.direction,
        )
    )
    pairs_by_id = {c.id: (c, s) for c, s in rows.all()}

    skipped_ids = [cid for cid in payload.card_ids if cid not in pairs_by_id]
    ordered_pairs = [pairs_by_id[cid] for cid in payload.card_ids if cid in pairs_by_id]

    db_session = await review_session_service.create_session(
        db, "custom", None, None, payload.direction
    )
    await db.commit()
    await db.refresh(db_session)

    cards = [_build_card_payload(c, s) for c, s in ordered_pairs]

    response: dict = {"session_id": db_session.id, "total_cards": len(cards), "cards": cards}
    if skipped_ids:
        response["skipped_ids"] = skipped_ids
    return response


@router.post("/session/{session_id}/rate")
async def rate_card(
    session_id: int,
    payload: RateRequest,
    db: AsyncSession = Depends(get_db),
):
    db_session = await review_session_service.get_session(db, session_id)
    if db_session is None or db_session.status != "active":
        raise HTTPException(404, "Session not found")
    if payload.rating not in (1, 2, 3, 4):
        raise HTTPException(400, "Rating must be 1 (Again), 2 (Hard), 3 (Good), or 4 (Easy)")

    schedule = await db.get(CardSchedule, payload.schedule_id)
    if not schedule:
        raise HTTPException(404, "Schedule not found")

    # Apply FSRS
    updates = await review_service.submit_review(db, schedule, payload.rating)

    # XP
    profile = await gamification_service.get_or_create_profile(db)
    xp_gain = gamification_service.XP_PER_REVIEW
    if payload.rating >= 3:
        xp_gain += gamification_service.XP_BONUS_GOOD_EASY
    xp_result = await gamification_service.add_xp(db, profile, xp_gain)

    await review_session_service.increment_session(db, session_id, xp_gain)

    total_reviews = await db.scalar(select(func.count(ReviewLog.id)))
    new_achievements = await gamification_service.check_and_award_achievements(
        db, profile, total_reviews or 0
    )

    await db.commit()

    return {
        "next_due": updates.get("fsrs_due").isoformat() if updates.get("fsrs_due") else None,
        "fsrs_state": updates.get("fsrs_state"),
        "xp_earned": xp_gain,
        "total_xp": xp_result["total_xp"],
        "level": xp_result["level"],
        "leveled_up": xp_result["leveled_up"],
        "new_achievements": new_achievements,
    }


@router.post("/session/{session_id}/end")
async def end_session(session_id: int, db: AsyncSession = Depends(get_db)):
    db_session = await review_session_service.get_session(db, session_id)
    if db_session is None:
        raise HTTPException(404, "Session not found")

    profile = await gamification_service.get_or_create_profile(db)
    streak_result = await gamification_service.update_streak(db, profile)

    # Only apply completion bonus and mark completed if still active; otherwise return existing totals.
    if db_session.status == "active":
        if db_session.cards_reviewed >= 10:
            await gamification_service.add_xp(db, profile, gamification_service.XP_SESSION_COMPLETE)
            db_session.xp_earned += gamification_service.XP_SESSION_COMPLETE
        await review_session_service.end_session(db, session_id)

    await db.commit()
    await db.refresh(db_session)

    return {
        "cards_reviewed": db_session.cards_reviewed,
        "xp_earned": db_session.xp_earned,
        "streak": streak_result["streak"],
        "streak_xp_bonus": streak_result["xp_earned"],
    }


@router.get("/sessions")
async def list_sessions(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Recent review sessions ordered by creation time descending."""
    result = await db.execute(
        select(ReviewSession)
        .order_by(ReviewSession.created_at.desc())
        .limit(limit)
    )
    sessions = result.scalars().all()
    return [
        {
            "id": s.id,
            "scope": s.scope,
            "scope_id": s.scope_id,
            "strategy": s.strategy,
            "direction": s.direction,
            "cards_reviewed": s.cards_reviewed,
            "xp_earned": s.xp_earned,
            "status": s.status,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        }
        for s in sessions
    ]
