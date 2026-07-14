from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.review_session import ReviewSession


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_session(
    db: AsyncSession,
    scope: str,
    scope_id: Optional[int],
    strategy: Optional[str],
    direction: str,
) -> ReviewSession:
    session = ReviewSession(
        scope=scope,
        scope_id=scope_id,
        strategy=strategy,
        direction=direction,
        cards_reviewed=0,
        xp_earned=0,
        status="active",
    )
    db.add(session)
    await db.flush()
    return session


async def get_session(db: AsyncSession, session_id: int) -> Optional[ReviewSession]:
    return await db.get(ReviewSession, session_id)


async def increment_session(
    db: AsyncSession, session_id: int, xp_delta: int
) -> Optional[ReviewSession]:
    session = await db.get(ReviewSession, session_id)
    if session is None:
        return None
    session.cards_reviewed += 1
    session.xp_earned += xp_delta
    session.updated_at = _utcnow()
    await db.flush()
    return session


async def end_session(
    db: AsyncSession, session_id: int, status: str = "completed"
) -> Optional[ReviewSession]:
    session = await db.get(ReviewSession, session_id)
    if session is None:
        return None
    session.status = status
    session.ended_at = _utcnow()
    session.updated_at = _utcnow()
    await db.flush()
    return session


async def abandon_stale_sessions(db: AsyncSession, older_than_hours: int = 24) -> int:
    cutoff = _utcnow() - timedelta(hours=older_than_hours)
    result = await db.execute(
        select(ReviewSession).where(
            ReviewSession.status == "active",
            ReviewSession.created_at < cutoff,
        )
    )
    stale = result.scalars().all()
    now = _utcnow()
    for s in stale:
        s.status = "abandoned"
        s.ended_at = now
        s.updated_at = now
    await db.flush()
    return len(stale)
