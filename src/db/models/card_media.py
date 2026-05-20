"""
Stub table for card media (images, audio, mnemonic images).
Schema is created now; upload endpoint is a future sprint.
"""
from typing import Optional, TYPE_CHECKING
from datetime import datetime
from sqlalchemy import String, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, utcnow

if TYPE_CHECKING:
    from .card import Card


class CardMedia(Base):
    __tablename__ = "card_media"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), nullable=False, index=True)

    media_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # image | audio | mnemonic_image

    storage_path: Mapped[str] = mapped_column(Text, nullable=False)  # relative to MEDIA_DIR
    alt_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    card: Mapped["Card"] = relationship(back_populates="media")
