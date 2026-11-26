from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from src.api.deps import get_db
from src.db.services import card_service, review_service, gamification_service
from src.db.services import review_session_service, daily_limits_service
from src.db.models.card import Card
from src.db.models.card_schedule import CardSchedule
from src.db.models.review_log import ReviewLog
from src.db.models.review_session import ReviewSession
from src.utils.card_overrides import apply_overrides, load_open_flag_targets, load_overrides
from src.utils.current_user import current_user

router = APIRouter(prefix="/review", tags=["review"])


class RateRequest(BaseModel):
    card_id: int
    schedule_id: int
    rating: int  # 1=Again 2=Hard 3=Good 4=Easy


class FromCardsRequest(BaseModel):
    card_ids: list[int]
    direction: str = "th_to_en"


def _build_card_payload(
    c: Card,
    s: CardSchedule,
    overrides: Optional[dict] = None,
    open_flags: Optional[list] = None,
) -> dict:
    import json as _json

    def _parse(v):
        if v is None:
            return None
        try:
            return _json.loads(v)
        except Exception:
            return None

    d = {
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
        "translation_status": c.translation_status,
        "translation_candidates": _parse(c.translation_candidates),
    }
    d = apply_overrides(d, overrides or {})
    d["open_flag_targets"] = open_flags or []
    d["has_open_flags"] = bool(open_flags)
    return d


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
async def get_due_summary(
    db: AsyncSession = Depends(get_db),
    x_timezone_offset: Optional[str] = Header(None),
):
    """Library-wide due/new counts, top-5 breakdowns, and today's capped workload.

    ``total_due``/``due_today``/``new_cards`` are the raw counts. ``today``
    is what today's limits actually leave to do; ``to_do_today`` is the
    headline number the dashboard shows.
    """
    tz = daily_limits_service.parse_tz_offset(x_timezone_offset)
    summary = await card_service.get_due_summary(db)
    budget = await daily_limits_service.get_budget(db, tz)
    await db.commit()  # get_budget may create the preferences row

    learning_due = summary["learning_due"]
    reviews_today = min(budget.review_due, budget.review_remaining)
    new_today = min(summary["new_cards"], budget.new_remaining)
    summary["today"] = budget.as_dict()
    summary["to_do_today"] = learning_due + reviews_today + new_today
    summary["today_breakdown"] = {
        "learning": learning_due,
        "reviews": reviews_today,
        "new": new_today,
    }
    return summary


@router.post("/session")
async def start_session(
    deck_id: Optional[int] = Query(None),
    topic_id: Optional[int] = Query(None),
    upload_id: Optional[int] = Query(None),
    scope: Optional[str] = Query(None),
    strategy: str = Query("due"),
    direction: str = Query("th_to_en"),
    extend: bool = Query(False, description="'Study more': go past today's limits"),
    db: AsyncSession = Depends(get_db),
    x_timezone_offset: Optional[str] = Header(None),
):
    """Start a review session.

    Due-card sessions (deck, topic, upload, library ``due``/``mixed``) respect
    the daily new-card and review limits; ``extend=true`` goes past them.
    ``at_risk`` and ``catch_up`` are explicit, fixed-size sessions and are
    not capped. ``held_back`` in the response counts due cards in scope left
    out only because of today's limits.
    """
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
    if scope == "library" and strategy not in ("due", "at_risk", "mixed", "catch_up"):
        raise HTTPException(422, f"Unknown strategy {strategy!r}. Use: due, at_risk, mixed, catch_up")

    # Mark any sessions left open longer than 24h as abandoned (housekeeping on natural traffic).
    await review_session_service.abandon_stale_sessions(db)

    tz = daily_limits_service.parse_tz_offset(x_timezone_offset)
    budget = await daily_limits_service.get_budget(db, tz, extend=extend)
    held_back = 0

    async def due_queue(q_scope: str, q_id: Optional[int], limit: int):
        nonlocal held_back
        queue = await daily_limits_service.get_due_queue(db, q_scope, q_id, direction, limit, budget)
        held_back = queue.held_back
        return queue

    if deck_id is not None:
        card_schedule_pairs = (await due_queue("deck", deck_id, 20)).pairs
        session_scope, scope_id, session_strategy = "deck", deck_id, None

    elif topic_id is not None:
        card_schedule_pairs = (await due_queue("topic", topic_id, 20)).pairs
        session_scope, scope_id, session_strategy = "topic", topic_id, None

    elif upload_id is not None:
        card_schedule_pairs = (await due_queue("upload", upload_id, 200)).pairs
        session_scope, scope_id, session_strategy = "upload", upload_id, None

    else:  # scope == "library"
        session_scope, scope_id, session_strategy = "library", None, strategy

        if strategy == "due":
            card_schedule_pairs = (await due_queue("library", None, 50)).pairs
        elif strategy == "at_risk":
            card_schedule_pairs = await card_service.get_at_risk_card_pairs(
                db, limit=20, direction=direction
            )
        elif strategy == "catch_up":
            card_schedule_pairs = await daily_limits_service.get_catch_up_queue(db, direction)
        else:  # mixed
            queue = await due_queue("library", None, 50)
            # At-risk cards are graduated reviews too, so they share the
            # review budget with the due part of the session.
            atrisk_room = max(0, budget.review_remaining - queue.reviews)
            atrisk_pairs = []
            if atrisk_room > 0:
                atrisk_pairs = await card_service.get_at_risk_card_pairs(
                    db, limit=min(20, atrisk_room), direction=direction
                )
            card_schedule_pairs = _interleave_mixed(queue.pairs, atrisk_pairs, limit=50)

    db_session = await review_session_service.create_session(
        db, session_scope, scope_id, session_strategy, direction
    )
    await db.commit()
    await db.refresh(db_session)

    user_id = current_user()
    session_card_ids = [c.id for c, _ in card_schedule_pairs]
    overrides_map = await load_overrides(db, session_card_ids, user_id)
    flags_map = await load_open_flag_targets(db, session_card_ids, user_id)
    cards = [
        _build_card_payload(c, s, overrides_map.get(c.id), flags_map.get(c.id))
        for c, s in card_schedule_pairs
    ]

    return {
        "session_id": db_session.id,
        "total_cards": len(cards),
        "cards": cards,
        "held_back": held_back,
        "today": budget.as_dict(),
    }


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

    user_id = current_user()
    ordered_card_ids = [c.id for c, _ in ordered_pairs]
    overrides_map = await load_overrides(db, ordered_card_ids, user_id)
    flags_map = await load_open_flag_targets(db, ordered_card_ids, user_id)
    cards = [
        _build_card_payload(c, s, overrides_map.get(c.id), flags_map.get(c.id))
        for c, s in ordered_pairs
    ]

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
