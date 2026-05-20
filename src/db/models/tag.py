from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base

if TYPE_CHECKING:
    from .card import Card


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("tags.id", ondelete="SET NULL"), nullable=True, index=True
    )

    parent: Mapped[Optional["Tag"]] = relationship(
        "Tag", remote_side="Tag.id", back_populates="children"
    )
    children: Mapped[List["Tag"]] = relationship("Tag", back_populates="parent")
    card_tags: Mapped[List["CardTag"]] = relationship(back_populates="tag", cascade="all, delete-orphan")


class CardTag(Base):
    __tablename__ = "card_tags"
    __table_args__ = (UniqueConstraint("card_id", "tag_id", name="uq_card_tag"),)

    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True)

    card: Mapped["Card"] = relationship(back_populates="card_tags")
    tag: Mapped["Tag"] = relationship(back_populates="card_tags")
