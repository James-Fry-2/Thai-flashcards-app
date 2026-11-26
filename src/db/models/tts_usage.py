from datetime import datetime
from sqlalchemy import Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, utcnow


class TTSUsage(Base):
    """One billed text-to-speech call (a cache miss). Cache hits cost
    nothing and are not recorded."""

    __tablename__ = "tts_usage"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    voice: Mapped[str] = mapped_column(String(80), nullable=False)
    rate: Mapped[str] = mapped_column(String(20), nullable=False)
    chars: Mapped[int] = mapped_column(Integer, nullable=False)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
