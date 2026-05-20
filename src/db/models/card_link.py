from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, ForeignKey, UniqueConstraint, Index, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, utcnow

if TYPE_CHECKING:
    from .card import Card

# Valid link types between cards
LINK_TYPES = {"related", "prerequisite", "antonym", "same_root", "variant"}

# These types are symmetric — creating A→B also creates B→A
SYMMETRIC_LINK_TYPES = {"related", "antonym"}


class CardLink(Base):
    __tablename__ = "card_links"
    __table_args__ = (
        UniqueConstraint("from_card_id", "to_card_id", "link_type", name="uq_card_link"),
        Index("ix_card_links_from", "from_card_id"),
        Index("ix_card_links_to", "to_card_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    from_card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), nullable=False
    )
    to_card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), nullable=False
    )
    link_type: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    from_card: Mapped["Card"] = relationship(
        foreign_keys=[from_card_id], back_populates="outgoing_links"
    )
    to_card: Mapped["Card"] = relationship(
        foreign_keys=[to_card_id], back_populates="incoming_links"
    )
