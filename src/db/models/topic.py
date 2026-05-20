from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, Text, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .card import Card


class Topic(Base, TimestampMixin):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    parent: Mapped[Optional["Topic"]] = relationship(
        "Topic", remote_side="Topic.id", back_populates="children"
    )
    children: Mapped[List["Topic"]] = relationship(
        "Topic", back_populates="parent", order_by="Topic.sort_order"
    )
    card_topics: Mapped[List["CardTopic"]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
    )


class CardTopic(Base):
    __tablename__ = "card_topics"

    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True, index=True
    )

    card: Mapped["Card"] = relationship(back_populates="card_topics")
    topic: Mapped["Topic"] = relationship(back_populates="card_topics")
