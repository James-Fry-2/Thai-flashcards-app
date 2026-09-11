"""
Mixed practice sessions: interleaves exercise types (src/practice/registry.py)
over a scoped set of cards. FSRS-free — writes nothing to CardSchedule,
ReviewLog, or review_sessions. See the practice-mode prompt ("The wall") for
why this file must never import from review_service.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.db.models.card import Card
from src.db.models.practice import PracticeSession, PracticeAttempt, PracticeOptionLog
from src.db.services import practice_service
from src.practice.registry import REGISTRY

router = APIRouter(prefix="/practice", tags=["practice"])


class OptionIn(BaseModel):
    card_id: int
    english: str
    source: str
    position: int


class AttemptRequest(BaseModel):
    session_id: int
    card_id: int
    exercise_type: str
    latency_ms: Optional[int] = None
    # Binary-graded exercises (e.g. mc_th_en):
    chosen_card_id: Optional[int] = None
    options: Optional[list[OptionIn]] = None
    # Self-rated exercises (e.g. recall_th_en):
    rating: Optional[int] = None


@router.post("/session")
async def start_practice_session(
    deck_id: Optional[int] = Query(None),
    topic_id: Optional[int] = Query(None),
    limit: int = Query(20, ge=1, le=50),
    exercise_types: Optional[list[str]] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if deck_id is not None:
        scope_type, scope_id = "deck", deck_id
    elif topic_id is not None:
        scope_type, scope_id = "topic", topic_id
    else:
        scope_type, scope_id = "library", None

    items = await practice_service.build_session(
        db,
        scope_type=scope_type,
        scope_id=scope_id,
        limit=limit,
        exercise_types=exercise_types,
    )

    session = PracticeSession(scope_type=scope_type, scope_id=scope_id, direction="th_to_en")
    db.add(session)
    await db.flush()
    await db.commit()

    return {
        "session_id": session.id,
        "direction": "th_to_en",
        "items": items,
    }


@router.post("/attempt")
async def submit_attempt(payload: AttemptRequest, db: AsyncSession = Depends(get_db)):
    exercise = REGISTRY.get(payload.exercise_type)
    if exercise is None:
        raise HTTPException(422, f"Unknown exercise_type '{payload.exercise_type}'")

    card = await db.get(Card, payload.card_id)
    if not card:
        raise HTTPException(404, f"Card {payload.card_id} not found")

    if exercise.grading == "binary":
        if payload.rating is not None:
            raise HTTPException(422, "rating is not valid for a binary-graded exercise_type")
        if payload.chosen_card_id is None or payload.options is None:
            raise HTTPException(
                422, "chosen_card_id and options are required for a binary-graded exercise_type"
            )
    elif exercise.grading == "self_rated":
        if payload.chosen_card_id is not None or payload.options is not None:
            raise HTTPException(
                422, "chosen_card_id/options are not valid for a self-rated exercise_type"
            )
        if payload.rating is None or not (1 <= payload.rating <= 4):
            raise HTTPException(422, "rating (1-4) is required for a self-rated exercise_type")

    outcome = (payload.chosen_card_id == payload.card_id) if exercise.grading == "binary" else None
    rating = payload.rating if exercise.grading == "self_rated" else None

    attempt = PracticeAttempt(
        session_id=payload.session_id,
        card_id=payload.card_id,
        exercise_type=payload.exercise_type,
        direction=exercise.direction,
        outcome=outcome,
        rating=rating,
        latency_ms=payload.latency_ms,
    )
    db.add(attempt)
    await db.flush()

    # The client posts the slate back rather than the server caching it —
    # a deliberate simplification for a single-user app. Revisit if
    # multi-user support lands (the log rows would need session ownership).
    if exercise.grading == "binary":
        for option in payload.options:
            db.add(PracticeOptionLog(
                attempt_id=attempt.id,
                option_card_id=option.card_id,
                option_text=None,
                option_source=option.source,
                position=option.position,
                is_target=option.card_id == payload.card_id,
                was_chosen=option.card_id == payload.chosen_card_id,
            ))

    await db.commit()

    return {
        "correct": outcome,
        "target_english": card.english,
    }


@router.post("/session/{session_id}/end")
async def end_practice_session(session_id: int, db: AsyncSession = Depends(get_db)):
    session = await db.get(PracticeSession, session_id)
    if not session:
        raise HTTPException(404, f"Practice session {session_id} not found")

    session.ended_at = datetime.now(timezone.utc)

    result = await db.execute(
        select(PracticeAttempt).where(PracticeAttempt.session_id == session_id)
    )
    attempts = list(result.scalars().all())
    await db.commit()

    by_exercise_type: dict[str, int] = {}
    for a in attempts:
        by_exercise_type[a.exercise_type] = by_exercise_type.get(a.exercise_type, 0) + 1

    # Kept separate, never blended into one score (decision 3 — MC yields a
    # boolean, recall yields a 1-4 self-rating, and the two aren't comparable).
    binary_attempts = [
        a for a in attempts if a.exercise_type in REGISTRY and REGISTRY[a.exercise_type].grading == "binary"
    ]
    binary_accuracy = (
        sum(1 for a in binary_attempts if a.outcome) / len(binary_attempts) if binary_attempts else None
    )

    self_rated_attempts = [
        a for a in attempts if a.exercise_type in REGISTRY and REGISTRY[a.exercise_type].grading == "self_rated"
    ]
    self_rated_rating_distribution: dict[int, int] = {}
    for a in self_rated_attempts:
        if a.rating is not None:
            self_rated_rating_distribution[a.rating] = self_rated_rating_distribution.get(a.rating, 0) + 1

    return {
        "total": len(attempts),
        "by_exercise_type": by_exercise_type,
        "binary_accuracy": binary_accuracy,
        "self_rated_rating_distribution": self_rated_rating_distribution,
    }
