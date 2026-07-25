from typing import Optional, List, TYPE_CHECKING
from datetime import datetime
from sqlalchemy import String, Text, Integer, Boolean, ForeignKey, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, utcnow

if TYPE_CHECKING:
    from .deck import Deck
    from .upload_page import UploadPage


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)  # pdf | image

    # single | book_parent | chapter_child
    kind: Mapped[str] = mapped_column(String(20), default="single", nullable=False)

    parent_upload_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("uploads.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # JSON-in-Text: chapter map (book_parent only)
    # New format: {"page_count": N, "boundaries": [{idx, page_start, title_en, title_th, include, confidence, signals, source, child_upload_id}]}
    # Legacy format (list): [{idx, chapter_label, page_start, page_end, child_upload_id}]
    chapter_map: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON-in-Text: per-page signal data from ensemble detection {"1": {char_count, font_outlier, ...}, ...}
    page_signals: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )  # pending | processing | done | failed | awaiting_confirmation

    stage: Mapped[str] = mapped_column(
        String(20), default="queued", nullable=False
    )  # queued | ocr | generating | tagging | complete | splitting | awaiting_confirmation | dispatching

    deck_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("decks.id", ondelete="SET NULL"), nullable=True
    )

    # Metadata inherited by children
    source_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    chapter_label: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    section_label: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    ocr_engine_used: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    ocr_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    text_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    cards_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    total_pages: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pages_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    deck: Mapped[Optional["Deck"]] = relationship(back_populates="uploads")
    pages: Mapped[List["UploadPage"]] = relationship(
        back_populates="upload", cascade="all, delete-orphan", order_by="UploadPage.page_index"
    )

    children: Mapped[List["Upload"]] = relationship(
        "Upload",
        foreign_keys=[parent_upload_id],
        back_populates="parent",
        cascade="all, delete-orphan",
    )
    parent: Mapped[Optional["Upload"]] = relationship(
        "Upload",
        foreign_keys=[parent_upload_id],
        back_populates="children",
        remote_side=[id],
    )
