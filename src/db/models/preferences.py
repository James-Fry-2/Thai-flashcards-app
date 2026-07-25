from datetime import datetime
from sqlalchemy import String, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, utcnow


class UserPreferences(Base):
    """Singleton (id=1) storing app-wide user preferences."""
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    romanization_display: Mapped[str] = mapped_column(
        String(20), nullable=False, default="source"
    )
    romanization_fallback: Mapped[str] = mapped_column(
        String(20), nullable=False, default="paiboon"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
