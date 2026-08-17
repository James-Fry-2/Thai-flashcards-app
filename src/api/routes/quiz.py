"""
Multiple-choice quiz drill mode (th_to_en). Standalone from the FSRS flip
review flow — writes nothing to CardSchedule or ReviewLog. See the quiz-mode
prompt for the full design rationale.
"""
import random
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.db.models.card import Card
from src.db.models.deck import Deck
from src.db.models.topic import CardTopic
from src.db.models.quiz_option_log import QuizOptionLog
from src.db.services import distractor_service

router = APIRouter(prefix="/quiz", tags=["quiz"])


class OptionIn(BaseModel):
    card_id: int
    english: str
    source: str
    position: int


class AnswerRequest(BaseModel):
    quiz_session_id: str
    target_card_id: int
    chosen_card_id: int
    latency_ms: Optional[int] = None
    options: list[OptionIn]


async def _select_target_cards(
    db: AsyncSession, deck_id: Optional[int], topic_id: Optional[int], limit: int
) -> list[Card]:
    """Target selection only — deck_id/topic_id narrow which cards are
    quizzed, never the distractor candidate pool (that's always the full
    library; see distractor_service)."""
    stmt = select(Card).join(Deck, Deck.id == Card.deck_id).where(Deck.deleted_at.is_(None))
    if deck_id is not None:
        stmt = stmt.where(Card.deck_id == deck_id)
    if topic_id is not None:
        stmt = stmt.join(CardTopic, CardTopic.card_id == Card.id).where(CardTopic.topic_id == topic_id)
    # Over-fetch: some targets will be skipped for a too-thin distractor pool.
    stmt = stmt.order_by(Card.id).limit(limit * 3)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/session")
async def start_quiz_session(
    deck_id: Optional[int] = Query(None),
    topic_id: Optional[int] = Query(None),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    candidates = await _select_target_cards(db, deck_id, topic_id, limit)
    random.shuffle(candidates)

    items = []
    for card in candidates:
        if len(items) >= limit:
            break
        slate = await distractor_service.build_option_slate(db, card.id, n_options=4)
        if len(slate) < 4:
            continue
        items.append({
            "card_id": card.id,
            "thai": card.thai,
            "romanization": card.romanization,
            "options": [
                {
                    "card_id": o["card_id"],
                    "english": o["english"],
                    "source": o["source"],
                    "position": o["position"],
                }
                for o in slate
            ],
        })

    return {
        "quiz_session_id": str(uuid.uuid4()),
        "direction": "th_to_en",
        "items": items,
    }


@router.post("/answer")
async def submit_quiz_answer(payload: AnswerRequest, db: AsyncSession = Depends(get_db)):
    target = await db.get(Card, payload.target_card_id)
    if not target:
        raise HTTPException(404, f"Card {payload.target_card_id} not found")

    # The client posts the slate back rather than the server caching it —
    # a deliberate simplification for a single-user app. Revisit if
    # multi-user support lands (the log rows would need session ownership).
    for option in payload.options:
        db.add(QuizOptionLog(
            quiz_session_id=payload.quiz_session_id,
            target_card_id=payload.target_card_id,
            option_card_id=option.card_id,
            option_text=None,
            option_source=option.source,
            position=option.position,
            is_target=option.card_id == payload.target_card_id,
            was_chosen=option.card_id == payload.chosen_card_id,
            direction="th_to_en",
            latency_ms=payload.latency_ms,
        ))
    await db.commit()

    return {
        "correct": payload.chosen_card_id == payload.target_card_id,
        "target_english": target.english,
    }
