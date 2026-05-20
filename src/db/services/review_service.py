import json
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.card_schedule import CardSchedule
from src.db.models.review_log import ReviewLog
from src.utils.fsrs_scheduler import apply_review


async def submit_review(
    db: AsyncSession,
    schedule: CardSchedule,
    rating: int,
) -> dict:
    """
    Apply a review rating (1=Again, 2=Hard, 3=Good, 4=Easy) to a card schedule.
    Returns the updated FSRS fields.
    """
    # Snapshot state before review for analytics
    state_before = json.dumps({
        "stability": schedule.fsrs_stability,
        "difficulty": schedule.fsrs_difficulty,
        "state": schedule.fsrs_state,
        "reps": schedule.fsrs_reps,
    })

    # Compute FSRS update
    updates = apply_review(schedule, rating)

    # Apply to schedule
    for key, value in updates.items():
        setattr(schedule, key, value)

    # Log the review
    log = ReviewLog(
        schedule_id=schedule.id,
        rating=rating,
        state_before=state_before,
    )
    db.add(log)
    await db.flush()

    return updates
