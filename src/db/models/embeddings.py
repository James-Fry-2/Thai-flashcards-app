"""
Embedding storage models — one table per entity type.

Storage encoding: float32 numpy array → .tobytes() → LargeBinary (SQLite BLOB).
Round-trip: numpy.frombuffer(record.embedding, dtype=numpy.float32)
~5x cheaper than JSON-encoded floats and faster to load.
"""
from datetime import datetime
from sqlalchemy import Text, LargeBinary, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, utcnow


class CardEmbedding(Base):
    __tablename__ = "card_embeddings"

    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True
    )
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    # float32 numpy array as raw bytes; decode with np.frombuffer(embedding, dtype=np.float32)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    text_hash: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class TopicEmbedding(Base):
    __tablename__ = "topic_embeddings"

    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True
    )
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    text_hash: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class TagEmbedding(Base):
    __tablename__ = "tag_embeddings"

    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    text_hash: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
