from typing import Optional, List, TYPE_CHECKING
from datetime import datetime, timezone
from sqlalchemy import String, Float, Integer, ForeignKey, UniqueConstraint, Index, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, utcnow

if TYPE_CHECKING:
    from .card import Card
    from .review_log import ReviewLog


class CardSchedule(Base):
    __tablename__ = "card_schedules"
    __table_args__ = (
        UniqueConstraint("card_id", "direction", name="uq_card_direction"),
        Index("idx_schedules_due", "fsrs_due"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), nullable=False, index=True)

    # Which direction this schedule tracks
    direction: Mapped[str] = mapped_column(
        String(20), default="th_to_en", nullable=False
    )  # th_to_en | en_to_th | listening

    # FSRS v5 state
    fsrs_stability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fsrs_difficulty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fsrs_due: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, default=utcnow)
    fsrs_last_review: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    fsrs_reps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fsrs_lapses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fsrs_state: Mapped[str] = mapped_column(
        String(20), default="new", nullable=False
    )  # new | learning | review | relearning

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    # Relationships
    card: Mapped["Card"] = relationship(back_populates="schedules")
    review_logs: Mapped[List["ReviewLog"]] = relationship(back_populates="schedule", cascade="all, delete-orphan")
