"""
Wrapper around the py-fsrs library (FSRS v5 algorithm).
Converts between our DB CardSchedule rows and py-fsrs Card objects.
"""
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.db.models.card_schedule import CardSchedule


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Return dt as a UTC-aware datetime; handles naive datetimes from SQLite."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def apply_review(schedule: "CardSchedule", rating: int) -> dict:
    """
    Apply a review rating to a CardSchedule and return updated FSRS fields.
    Rating: 1=Again, 2=Hard, 3=Good, 4=Easy
    """
    from fsrs import FSRS, Card as FSRSCard, Rating, State

    fsrs = FSRS()

    # Build py-fsrs Card from DB state
    card = FSRSCard()
    if schedule.fsrs_stability is not None:
        card.stability = schedule.fsrs_stability
    if schedule.fsrs_difficulty is not None:
        card.difficulty = schedule.fsrs_difficulty
    card.reps = schedule.fsrs_reps
    card.lapses = schedule.fsrs_lapses
    # SQLite returns naive datetimes even for timezone=True columns; make them UTC-aware
    # so py-fsrs can subtract them from datetime.now(timezone.utc) without a TypeError.
    if schedule.fsrs_last_review:
        card.last_review = _ensure_utc(schedule.fsrs_last_review)
    if schedule.fsrs_due:
        card.due = _ensure_utc(schedule.fsrs_due)

    # Map state string to FSRSState enum
    state_map = {
        "new": State.New,
        "learning": State.Learning,
        "review": State.Review,
        "relearning": State.Relearning,
    }
    card.state = state_map.get(schedule.fsrs_state, State.New)

    # Apply the review
    now = datetime.now(timezone.utc)
    fsrs_rating = Rating(rating)
    scheduling_cards = fsrs.repeat(card, now)
    updated = scheduling_cards[fsrs_rating].card

    # Map State enum back to string
    state_str_map = {
        State.New: "new",
        State.Learning: "learning",
        State.Review: "review",
        State.Relearning: "relearning",
    }

    return {
        "fsrs_stability": updated.stability,
        "fsrs_difficulty": updated.difficulty,
        "fsrs_due": updated.due,
        "fsrs_last_review": now,
        "fsrs_reps": updated.reps,
        "fsrs_lapses": updated.lapses,
        "fsrs_state": state_str_map.get(updated.state, "review"),
    }
