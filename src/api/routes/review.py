from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from src.api.deps import get_db
from src.db.services import card_service, review_service, gamification_service
from src.db.models.card_schedule import CardSchedule
from src.db.models.review_log import ReviewLog

router = APIRouter(prefix="/review", tags=["review"])

# In-memory session store (sufficient for single-user; a DB table would be overkill here)
# Maps session_id → {deck_id, direction, card_ids_remaining, cards_reviewed, xp_earned}
_sessions: dict = {}
_next_session_id = 1


class RateRequest(BaseModel):
    card_id: int
    schedule_id: int
    rating: int  # 1=Again 2=Hard 3=Good 4=Easy


@router.post("/session")
async def start_session(
    deck_id: int,
    direction: str = "th_to_en",
    db: AsyncSession = Depends(get_db),
):
    global _next_session_id
    card_schedule_pairs = await card_service.get_due_cards(db, deck_id, limit=20, direction=direction)

    session_id = _next_session_id
    _next_session_id += 1

    _sessions[session_id] = {
        "deck_id": deck_id,
        "direction": direction,
        "cards_reviewed": 0,
        "xp_earned": 0,
    }

    cards = [
        {
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
        }
        for c, s in card_schedule_pairs
    ]

    return {
        "session_id": session_id,
        "total_cards": len(cards),
        "cards": cards,
    }


@router.post("/session/{session_id}/rate")
async def rate_card(
    session_id: int,
    payload: RateRequest,
    db: AsyncSession = Depends(get_db),
):
    if session_id not in _sessions:
        raise HTTPException(404, "Session not found")
    if payload.rating not in (1, 2, 3, 4):
        raise HTTPException(400, "Rating must be 1 (Again), 2 (Hard), 3 (Good), or 4 (Easy)")

    session = _sessions[session_id]

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

    session["cards_reviewed"] += 1
    session["xp_earned"] += xp_gain

    # Check achievements (use total review count from review_log)
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
    if session_id not in _sessions:
        raise HTTPException(404, "Session not found")

    session = _sessions.pop(session_id)

    profile = await gamification_service.get_or_create_profile(db)

    # Streak + session completion bonus
    streak_result = await gamification_service.update_streak(db, profile)

    if session["cards_reviewed"] >= 10:
        await gamification_service.add_xp(db, profile, gamification_service.XP_SESSION_COMPLETE)
        session["xp_earned"] += gamification_service.XP_SESSION_COMPLETE

    await db.commit()

    return {
        "cards_reviewed": session["cards_reviewed"],
        "xp_earned": session["xp_earned"],
        "streak": streak_result["streak"],
        "streak_xp_bonus": streak_result["xp_earned"],
    }
