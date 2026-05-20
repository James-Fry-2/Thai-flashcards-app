from typing import Optional, List
from datetime import datetime, date
from sqlalchemy import String, Text, Integer, Date, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, utcnow


class UserProfile(Base):
    """Single-row table (id=1) tracking the self-hosted user's gamification state."""
    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    streak_current: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    streak_longest: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    streak_last_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    user_achievements: Mapped[List["UserAchievement"]] = relationship(back_populates="profile", cascade="all, delete-orphan")


class Achievement(Base):
    __tablename__ = "achievements"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    xp_reward: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    icon: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # emoji or icon name

    user_achievements: Mapped[List["UserAchievement"]] = relationship(back_populates="achievement")


class UserAchievement(Base):
    __tablename__ = "user_achievements"

    achievement_key: Mapped[str] = mapped_column(
        ForeignKey("achievements.key", ondelete="CASCADE"), primary_key=True
    )
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    profile_id: Mapped[int] = mapped_column(ForeignKey("user_profile.id", ondelete="CASCADE"), nullable=False, default=1)
    profile: Mapped["UserProfile"] = relationship(back_populates="user_achievements")
    achievement: Mapped["Achievement"] = relationship(back_populates="user_achievements")
