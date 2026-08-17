from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Integer, Boolean, ForeignKey, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, utcnow


class QuizOptionLog(Base):
    """One row per option presented in a multiple-choice quiz item (four rows
    per answered item). See prompt: nullable option_card_id/option_text is a
    deliberate forward-compat seam for a future non-card (e.g. lexicon-sourced)
    distractor source — v1 always populates option_card_id and leaves
    option_text NULL."""

    __tablename__ = "quiz_option_log"
    __table_args__ = (
        Index("ix_quiz_option_log_target_option", "target_card_id", "option_card_id"),
        Index("ix_quiz_option_log_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    quiz_session_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    target_card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    option_card_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), nullable=True, index=True
    )
    option_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    option_source: Mapped[str] = mapped_column(String(20), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_target: Mapped[bool] = mapped_column(Boolean, nullable=False)
    was_chosen: Mapped[bool] = mapped_column(Boolean, nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="th_to_en")
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
