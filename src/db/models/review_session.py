from typing import Optional
from datetime import datetime
from sqlalchemy import Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, TimestampMixin


class ReviewSession(Base, TimestampMixin):
    __tablename__ = "review_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    strategy: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="th_to_en")
    cards_reviewed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    xp_earned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
