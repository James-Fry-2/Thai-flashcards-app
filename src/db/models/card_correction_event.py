from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Integer, ForeignKey, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, utcnow


class CardCorrectionEvent(Base):
    """Append-only history of every correction decision (triage or drawer).

    Never updated or deleted — undo() writes a compensating event with
    `reverts_event_id` set, it never mutates or removes the original row.
    `card_override` (see card_override.py) stays the *current* per-user
    state; this table is the *history* underneath it. Every override write
    that goes through correction_service.apply_decision() appends one of
    these in the same transaction.

    `card_id` uses SET NULL (unlike card_flag/card_override's CASCADE)
    because a correction's value is still useful after the card that
    produced it is deleted — "N people corrected ไม่เป็นไร from 'you're
    welcome'" survives any one card, which is why `thai_key` and
    `from_value` are denormalised onto the row rather than only reachable
    via a join to `cards`.
    """

    __tablename__ = "card_correction_event"
    __table_args__ = (
        Index("ix_card_correction_event_user_created", "user_id", "created_at"),
        Index("ix_card_correction_event_thai_target", "thai_key", "target"),
        Index("ix_card_correction_event_thai_target_norm", "thai_key", "target", "from_norm"),
        Index("ix_card_correction_event_batch_id", "batch_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    card_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("cards.id", ondelete="SET NULL"), nullable=True
    )
    thai_key: Mapped[str] = mapped_column(String, nullable=False)
    target: Mapped[str] = mapped_column(String(20), nullable=False)  # translation|compound|romanization|other
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # keep|correct|edit_gloss|suppress|llm_fill|dismiss_flag|undo
    from_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON snapshot, effective value before
    to_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON snapshot, value after (null for keep/dismiss_flag)
    from_norm: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # normalised comparison key from from_value
    prev_override: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # prior card_override.payload, for undo
    ai_verdict: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    ai_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # triage|drawer
    batch_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    applied_from_event_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("card_correction_event.id"), nullable=True
    )
    reverts_event_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("card_correction_event.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
