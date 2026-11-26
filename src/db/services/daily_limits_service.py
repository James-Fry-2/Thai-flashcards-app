"""Daily workload caps and catch-up mode.

The review queue used to treat every unstudied card as "due", so a single
book upload could put thousands of cards in today's queue, and a few missed
days left a pile that only grew. This module keeps each day's workload
bounded:

- **New cards** are capped at ``daily_new_limit`` per day.
- **Graduated reviews** (state ``review``) are capped at ``daily_review_limit``.
- **Learning / relearning** cards are never capped: they are mid-step and
  skipping them would undo work already done today.

What has been done today is counted from ``review_log`` (the ``state`` in
``state_before`` says whether a log was a new card or a review), so no
separate counter table is needed. A "day" runs from 04:00 to 04:00 in the
user's local time, so a late-night session counts toward the evening it
started in. The browser sends its UTC offset in the ``X-Timezone-Offset``
header (minutes, as returned by ``Date.getTimezoneOffset()``).

**Catch-up mode** turns on when more graduated reviews are due than one
day's review limit. While it is on, new cards are paused (adding new cards
to a backlog only makes it grow) and a catch-up session offers a fixed-size
batch of overdue cards ordered by how likely they still are to be
remembered: cards that are only a little overdue relative to their
stability come first, because reviewing them now saves them, whereas cards
that are long forgotten cost the same to relearn tomorrow.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.card import Card
from src.db.models.card_schedule import CardSchedule
from src.db.models.review_log import ReviewLog
from src.db.services import preferences_service

DAY_ROLLOVER_HOUR = 4
# Size of one catch-up session; small on purpose so it feels finishable.
CATCH_UP_SESSION_SIZE = 30
# How many new cards "Study more" adds once today's new-card limit is used up.
EXTEND_NEW_CARDS = 10

_LEARNING_STATES = ("learning", "relearning")
# Max |offset| a browser can report (UTC-12 .. UTC+14).
_MAX_OFFSET_MINUTES = 14 * 60


def parse_tz_offset(raw: Optional[str]) -> int:
    """Parse an ``X-Timezone-Offset`` header; anything invalid means UTC."""
    if raw is None:
        return 0
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        return 0
    if abs(minutes) > _MAX_OFFSET_MINUTES:
        return 0
    return minutes


def day_start_utc(tz_offset_minutes: int = 0, now: Optional[datetime] = None) -> datetime:
    """UTC instant at which the user's current study day began (local 04:00).

    ``tz_offset_minutes`` follows the JS ``getTimezoneOffset()`` convention:
    UTC minus local time, so Bangkok (UTC+7) is ``-420``.
    """
    now = now or datetime.now(timezone.utc)
    offset = timedelta(minutes=tz_offset_minutes)
    local_now = now - offset
    start_local = local_now.replace(hour=DAY_ROLLOVER_HOUR, minute=0, second=0, microsecond=0)
    if local_now < start_local:
        start_local -= timedelta(days=1)
    return start_local + offset


@dataclass
class DailyBudget:
    new_limit: int
    review_limit: int
    new_done: int
    reviews_done: int
    new_remaining: int
    review_remaining: int
    review_due: int  # graduated reviews due now, all directions
    catch_up: bool  # backlog bigger than one day's review limit
    extended: bool = False

    @property
    def catch_up_days(self) -> int:
        """Rough days to clear the backlog at the daily limit (ignores new dues)."""
        if not self.catch_up or self.review_limit <= 0:
            return 0
        return math.ceil(self.review_due / self.review_limit)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["catch_up_days"] = self.catch_up_days
        return d


async def get_budget(
    db: AsyncSession,
    tz_offset_minutes: int = 0,
    extend: bool = False,
    now: Optional[datetime] = None,
) -> DailyBudget:
    """What is left of today's new-card and review allowance.

    ``extend=True`` is the "Study more" path: it grants up to
    ``EXTEND_NEW_CARDS`` new cards even when the day's limit (or catch-up
    mode) would allow none, and lifts the review cap.
    """
    now = now or datetime.now(timezone.utc)
    prefs = await preferences_service.get_preferences(db)
    start = day_start_utc(tz_offset_minutes, now)

    state_before = func.json_extract(ReviewLog.state_before, "$.state")
    new_done = await db.scalar(
        select(func.count(func.distinct(ReviewLog.schedule_id)))
        .where(ReviewLog.reviewed_at >= start, state_before == "new")
    ) or 0
    reviews_done = await db.scalar(
        select(func.count(ReviewLog.id))
        .where(ReviewLog.reviewed_at >= start, state_before == "review")
    ) or 0

    review_due = await db.scalar(
        select(func.count(CardSchedule.id))
        .where(CardSchedule.fsrs_state == "review", CardSchedule.fsrs_due <= now)
    ) or 0

    new_limit = prefs.daily_new_limit
    review_limit = prefs.daily_review_limit
    catch_up = review_due > review_limit

    new_remaining = max(0, new_limit - new_done)
    review_remaining = max(0, review_limit - reviews_done)
    if catch_up:
        new_remaining = 0

    if extend:
        new_remaining = max(new_remaining, EXTEND_NEW_CARDS)
        review_remaining = max(review_remaining, review_due)

    return DailyBudget(
        new_limit=new_limit,
        review_limit=review_limit,
        new_done=new_done,
        reviews_done=reviews_done,
        new_remaining=new_remaining,
        review_remaining=review_remaining,
        review_due=review_due,
        catch_up=catch_up,
        extended=extend,
    )


# ---------------------------------------------------------------------------
# Queue building
# ---------------------------------------------------------------------------

def _scoped(stmt, scope: str, scope_id: Optional[int]):
    """Restrict a Card+CardSchedule select to a deck / topic / upload / library."""
    if scope == "deck":
        return stmt.where(Card.deck_id == scope_id)
    if scope == "topic":
        from src.db.models.topic import CardTopic
        return stmt.join(CardTopic, CardTopic.card_id == Card.id).where(CardTopic.topic_id == scope_id)
    if scope == "upload":
        return stmt.where(Card.source_upload_id == scope_id)
    if scope == "library":
        return stmt
    raise ValueError(f"unknown scope {scope!r}")


def _base(scope: str, scope_id: Optional[int], direction: str):
    stmt = (
        select(Card, CardSchedule)
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(CardSchedule.direction == direction)
    )
    return _scoped(stmt, scope, scope_id)


async def _count(db: AsyncSession, scope: str, scope_id: Optional[int], direction: str, *where) -> int:
    stmt = (
        select(func.count(CardSchedule.id))
        .select_from(Card)
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(CardSchedule.direction == direction, *where)
    )
    return await db.scalar(_scoped(stmt, scope, scope_id)) or 0


@dataclass
class DueQueue:
    pairs: list  # list[tuple[Card, CardSchedule]]
    learning: int
    reviews: int
    new: int
    # Due cards in this scope left out only because today's limits are used up.
    held_back: int


async def get_due_queue(
    db: AsyncSession,
    scope: str,
    scope_id: Optional[int],
    direction: str,
    limit: int,
    budget: DailyBudget,
    now: Optional[datetime] = None,
) -> DueQueue:
    """Build a review session within today's limits.

    Order: learning/relearning first (time-sensitive), then due reviews by
    due date, then new cards. Each bucket takes from what the session still
    has room for.
    """
    now = now or datetime.now(timezone.utc)

    learning_rows = (await db.execute(
        _base(scope, scope_id, direction)
        .where(CardSchedule.fsrs_state.in_(_LEARNING_STATES), CardSchedule.fsrs_due <= now)
        .order_by(CardSchedule.fsrs_due.asc())
        .limit(limit)
    )).all()
    room = limit - len(learning_rows)

    # A bucket is "capped" when today's budget, not the session size, is
    # what limits it; only then do left-over cards count as held back.
    review_capped = budget.review_remaining < room
    review_take = min(room, budget.review_remaining)
    review_rows = []
    if review_take > 0:
        review_rows = (await db.execute(
            _base(scope, scope_id, direction)
            .where(CardSchedule.fsrs_state == "review", CardSchedule.fsrs_due <= now)
            .order_by(CardSchedule.fsrs_due.asc())
            .limit(review_take)
        )).all()
    room -= len(review_rows)

    new_capped = budget.new_remaining < room
    new_take = min(room, budget.new_remaining)
    new_rows = []
    if new_take > 0:
        new_rows = (await db.execute(
            _base(scope, scope_id, direction)
            .where(CardSchedule.fsrs_state == "new")
            .order_by(CardSchedule.fsrs_due.asc(), Card.id.asc())
            .limit(new_take)
        )).all()

    held_back = 0
    if review_capped:
        review_in_scope = await _count(
            db, scope, scope_id, direction,
            CardSchedule.fsrs_state == "review", CardSchedule.fsrs_due <= now,
        )
        held_back += max(0, review_in_scope - len(review_rows))
    if new_capped:
        new_in_scope = await _count(db, scope, scope_id, direction, CardSchedule.fsrs_state == "new")
        held_back += max(0, new_in_scope - len(new_rows))

    pairs = [(r[0], r[1]) for r in (*learning_rows, *review_rows, *new_rows)]
    return DueQueue(
        pairs=pairs,
        learning=len(learning_rows),
        reviews=len(review_rows),
        new=len(new_rows),
        held_back=held_back,
    )


async def get_catch_up_queue(
    db: AsyncSession,
    direction: str,
    limit: int = CATCH_UP_SESSION_SIZE,
    now: Optional[datetime] = None,
) -> list:
    """Overdue reviews most worth saving first.

    Sorted by elapsed-days / stability ascending, which is the same order as
    FSRS retrievability descending (retrievability falls monotonically with
    t/S), without depending on the FSRS version's decay constants.
    """
    now = now or datetime.now(timezone.utc)
    now_jd = func.julianday(now.replace(tzinfo=None).isoformat(sep=" "))
    elapsed_over_stability = (
        (now_jd - func.julianday(CardSchedule.fsrs_last_review)) / CardSchedule.fsrs_stability
    )
    rows = (await db.execute(
        select(Card, CardSchedule)
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(
            CardSchedule.direction == direction,
            CardSchedule.fsrs_state == "review",
            CardSchedule.fsrs_due <= now,
        )
        .order_by(
            # Rows missing stability/last_review can't be scored: put them last.
            (CardSchedule.fsrs_stability.is_(None) | CardSchedule.fsrs_last_review.is_(None)).asc(),
            elapsed_over_stability.asc(),
            CardSchedule.fsrs_due.asc(),
        )
        .limit(limit)
    )).all()
    return [(r[0], r[1]) for r in rows]
