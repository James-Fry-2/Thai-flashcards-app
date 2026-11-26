from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, utcnow


class GeneratedText(Base):
    """A dialogue or set of example sentences written by Claude around the
    vocabulary of a topic or chapter, for reading practice.

    ``lines`` is JSON: [{speaker, word, thai, english}]. ``speaker`` is set
    for dialogues, ``word`` (the target word a sentence illustrates) for
    example sentences. ``check`` is JSON from the second, checking pass:
    {checked, fixed, notes: [{index, note}]}.
    """

    __tablename__ = "generated_text"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # dialogue | sentences
    scope: Mapped[str] = mapped_column(String(20), nullable=False)  # topic | upload
    scope_id: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    setting: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lines: Mapped[str] = mapped_column(Text, nullable=False)
    target_words: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list of thai
    check: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # JSON list of model calls: [{step, model, input_tokens, output_tokens,
    # cache_*_input_tokens, cost}] (see src/llm/pricing.py).
    usage: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
