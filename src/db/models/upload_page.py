from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Text, Integer, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base

if TYPE_CHECKING:
    from .upload import Upload


class UploadPage(Base):
    __tablename__ = "upload_pages"
    __table_args__ = (UniqueConstraint("upload_id", "page_index", name="uq_upload_pages_upload_page"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    upload_id: Mapped[int] = mapped_column(
        ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    engine_used: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    upload: Mapped["Upload"] = relationship(back_populates="pages")
