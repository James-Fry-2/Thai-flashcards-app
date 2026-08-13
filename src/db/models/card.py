from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, Text, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .deck import Deck
    from .card_schedule import CardSchedule
    from .card_media import CardMedia
    from .tag import CardTag
    from .upload import Upload
    from .card_link import CardLink
    from .topic import CardTopic


class Card(Base, TimestampMixin):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), nullable=False, index=True)

    # Core content
    thai: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    romanization: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # effective/display (resolved)
    romanization_source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # LLM-copied from material
    romanization_paiboon: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    romanization_rtgs: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    romanization_ipa: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    romanization_manual: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # user hand-edit; top precedence
    english: Mapped[str] = mapped_column(Text, nullable=False)
    example_thai: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    example_english: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Thai script analysis (populated at card creation, backfilled via script)
    syllable_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tone_pattern: Mapped[Optional[str]] = mapped_column(Text, nullable=True)        # JSON-encoded list[str]
    consonant_classes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON-encoded list[str]
    has_cluster: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    has_rare_consonant: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    has_silent_mark: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    script_analysis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)     # JSON-encoded list[dict]

    # Compound breakdown (populated at card creation, backfilled via script)
    compound_breakdown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON-encoded list[dict]
    is_compound: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # Translation check (populated at card creation, backfilled via script)
    translation_status: Mapped[str] = mapped_column(Text, nullable=False, default="unverified", index=True)
    translation_candidates: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON-encoded list[str]

    card_type: Mapped[str] = mapped_column(
        String(20), default="vocab", nullable=False
    )  # vocab | phrase | grammar

    # Source provenance
    source_upload_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("uploads.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    deck: Mapped["Deck"] = relationship(back_populates="cards")
    schedules: Mapped[List["CardSchedule"]] = relationship(back_populates="card", cascade="all, delete-orphan")
    media: Mapped[List["CardMedia"]] = relationship(back_populates="card", cascade="all, delete-orphan")
    card_tags: Mapped[List["CardTag"]] = relationship(back_populates="card", cascade="all, delete-orphan")
    source_upload: Mapped[Optional["Upload"]] = relationship(foreign_keys=[source_upload_id])
    outgoing_links: Mapped[List["CardLink"]] = relationship(
        foreign_keys="CardLink.from_card_id", back_populates="from_card", cascade="all, delete-orphan"
    )
    incoming_links: Mapped[List["CardLink"]] = relationship(
        foreign_keys="CardLink.to_card_id", back_populates="to_card", cascade="all, delete-orphan"
    )
    card_topics: Mapped[List["CardTopic"]] = relationship(back_populates="card", cascade="all, delete-orphan")
