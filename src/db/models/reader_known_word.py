from datetime import datetime
from sqlalchemy import Integer, Text, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, utcnow


class ReaderKnownWord(Base):
    """A word the learner marked "I know this" in the reader, without a card.

    Function words like ครับ or ที่ are usually known long before anyone makes
    a card for them; without this, every page's "% known" score would stay
    misleadingly low.
    """

    __tablename__ = "reader_known_word"
    __table_args__ = (UniqueConstraint("user_id", "thai", name="uq_reader_known_word_user_thai"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    thai: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
