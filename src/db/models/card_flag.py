from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Integer, ForeignKey, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, utcnow


class CardFlag(Base):
    """A user's report that something on a card is wrong. Carries no
    correction — it is the input to a future admin review queue, not a
    display-value change. See CardOverride for the private per-user layer
    that actually changes what's shown."""

    __tablename__ = "card_flag"
    __table_args__ = (
        Index("ix_card_flag_user_status", "user_id", "status"),
        Index("ix_card_flag_card_target", "card_id", "target"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target: Mapped[str] = mapped_column(String(20), nullable=False)  # translation|compound|romanization|example|other
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    flagged_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON snapshot at flag time
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")  # open|resolved|dismissed
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
