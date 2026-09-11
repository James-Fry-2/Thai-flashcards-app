from datetime import datetime
from sqlalchemy import String, Text, Integer, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, utcnow


class CardOverride(Base):
    """A user's private display-layer correction for one field on one card.
    Never mutates `cards` — src/utils/card_overrides.py resolves this on top
    of the derived card dict at read time, the same shape as
    romanization.py's resolve_effective(values, prefs)."""

    __tablename__ = "card_override"
    __table_args__ = (
        UniqueConstraint("user_id", "card_id", "target", name="uq_card_override_user_card_target"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), nullable=False
    )
    target: Mapped[str] = mapped_column(String(20), nullable=False)  # translation|compound
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON, shape depends on target
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
