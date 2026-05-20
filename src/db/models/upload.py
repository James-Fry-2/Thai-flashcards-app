from typing import Optional, List, TYPE_CHECKING
from datetime import datetime
from sqlalchemy import String, Text, Integer, ForeignKey, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, utcnow

if TYPE_CHECKING:
    from .deck import Deck


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)  # pdf | image

    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )  # pending | processing | done | failed

    deck_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("decks.id", ondelete="SET NULL"), nullable=True
    )

    ocr_engine_used: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    ocr_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    text_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    cards_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    deck: Mapped[Optional["Deck"]] = relationship(back_populates="uploads")
