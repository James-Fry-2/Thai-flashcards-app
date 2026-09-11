from datetime import datetime
from typing import Optional
from sqlalchemy import (
    String, Text, Integer, Boolean, ForeignKey, DateTime, Index, CheckConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, utcnow


class PracticeSession(Base):
    """One mixed-exercise practice run. Distinct from `ReviewSession` — this
    is the FSRS-free drill flow; nothing here ever touches CardSchedule,
    ReviewLog, or review_sessions."""

    __tablename__ = "practice_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "deck" | "topic" | "library"
    scope_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class PracticeAttempt(Base):
    """One card's attempt within a practice session, for any exercise type.

    `outcome` (binary-graded exercises, e.g. mc_th_en) and `rating`
    (self-rated exercises, e.g. recall_th_en) are both nullable and neither
    is derived from the other — do not map outcome=True -> rating=3 and do
    not add a unified score column. MC yields a boolean; recall yields a
    1-4 self-rating; collapsing them into one scale discards the thing
    being measured.

    `latency_ms` is not decoration: on mc_th_en it's what separates genuine
    confusion (fast wrong) from guessing (slow wrong), and guessing is the
    main pollutant in that dataset.
    """

    __tablename__ = "practice_attempts"
    __table_args__ = (
        Index("ix_practice_attempts_session_id", "session_id"),
        Index("ix_practice_attempts_card_id", "card_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("practice_sessions.id", ondelete="CASCADE"), nullable=False
    )
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), nullable=False
    )
    exercise_type: Mapped[str] = mapped_column(String(30), nullable=False)  # registry key
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class PracticeOptionLog(Base):
    """One row per option presented in a binary-graded (e.g. mc_th_en) item —
    four rows per answered item. `target_card_id`, `direction` and
    `latency_ms` live on the parent PracticeAttempt and are not duplicated
    here; the confusion query joins back through `attempt_id`.

    `option_card_id`/`option_text` are both nullable — a deliberate
    forward-compat seam for a future non-card (e.g. lexicon-sourced)
    distractor source. v1 always populates option_card_id and leaves
    option_text NULL; the CheckConstraint below only requires that at least
    one of the two is set, not that a specific one is.
    """

    __tablename__ = "practice_option_log"
    __table_args__ = (
        Index("ix_practice_option_log_attempt_id", "attempt_id"),
        Index("ix_practice_option_log_option_card_id", "option_card_id"),
        CheckConstraint(
            "option_card_id IS NOT NULL OR option_text IS NOT NULL",
            name="ck_practice_option_log_card_or_text",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("practice_attempts.id", ondelete="CASCADE"), nullable=False
    )
    option_card_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), nullable=True
    )
    option_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    option_source: Mapped[str] = mapped_column(String(20), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_target: Mapped[bool] = mapped_column(Boolean, nullable=False)
    was_chosen: Mapped[bool] = mapped_column(Boolean, nullable=False)
