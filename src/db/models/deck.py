from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .card import Card
    from .upload import Upload


class Deck(Base, TimestampMixin):
    __tablename__ = "decks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_lang: Mapped[str] = mapped_column(String(10), default="th", nullable=False)
    target_lang: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    cards: Mapped[List["Card"]] = relationship(back_populates="deck", cascade="all, delete-orphan")
    uploads: Mapped[List["Upload"]] = relationship(back_populates="deck")
