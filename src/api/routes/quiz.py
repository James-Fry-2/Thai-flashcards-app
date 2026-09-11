"""
/quiz is a restricted practice session (mc_th_en only), not a parallel
implementation — the URL, UI, and entry point survive for continuity, but
the data now lives in practice_sessions/practice_attempts/practice_option_log
alongside every other practice session. See the practice-mode prompt,
decision 1.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.api.routes.practice import AttemptRequest, start_practice_session, submit_attempt

router = APIRouter(prefix="/quiz", tags=["quiz"])


@router.post("/session")
async def start_quiz_session(
    deck_id: Optional[int] = Query(None),
    topic_id: Optional[int] = Query(None),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    return await start_practice_session(
        deck_id=deck_id, topic_id=topic_id, limit=limit, exercise_types=["mc_th_en"], db=db
    )


@router.post("/answer")
async def submit_quiz_answer(payload: AttemptRequest, db: AsyncSession = Depends(get_db)):
    return await submit_attempt(payload, db)
