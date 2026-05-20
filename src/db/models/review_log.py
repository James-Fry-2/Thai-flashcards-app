from typing import Optional, TYPE_CHECKING
from datetime import datetime
from sqlalchemy import Integer, Text, ForeignKey, DateTime, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, utcnow

if TYPE_CHECKING:
    from .card_schedule import CardSchedule


class ReviewLog(Base):
    __tablename__ = "review_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("card_schedules.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # FSRS ratings: 1=Again 2=Hard 3=Good 4=Easy
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    # JSON snapshot of FSRS state before this review (for analytics/debugging)
    state_before: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    schedule: Mapped["CardSchedule"] = relationship(back_populates="review_logs")
