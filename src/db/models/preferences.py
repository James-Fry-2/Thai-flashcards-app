from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Boolean
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
    # Daily workload caps (see src/db/services/daily_limits_service.py).
    daily_new_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )
    daily_review_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    # Text-to-speech playback (see src/db/services/tts_service.py).
    tts_autoplay_on_reveal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    tts_default_speed: Mapped[str] = mapped_column(
        String(10), nullable=False, default="normal", server_default="normal"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
