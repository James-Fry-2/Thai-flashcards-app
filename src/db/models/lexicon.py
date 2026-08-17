from typing import Optional
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class Lexicon(Base):
    __tablename__ = "lexicon"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    thai: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    romanization: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    english: Mapped[str] = mapped_column(Text, nullable=False)
    pos: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="volubilis", nullable=False)
    scientific_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    level: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    usage: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
