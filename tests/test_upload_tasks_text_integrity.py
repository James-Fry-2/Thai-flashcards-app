"""
Tests for the text-integrity guard wired into the upload pipeline
(src/tasks/upload_tasks.py): the OCR-stage text-layer acceptance check, and
the card-generation guard that repairs LLM-copied Thai/romanization before
generate_all() runs and files a review flag when a repair can't be verified.

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_upload_tasks_text_integrity.py -v
"""
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.config.settings import Settings
from src.db.models import Base
from src.db.models.card import Card
from src.db.models.card_flag import CardFlag
from src.db.models.deck import Deck
from src.db.models.upload import Upload
from src.db.models.upload_page import UploadPage
from src.ocr.confidence import OcrResult
from src.tasks.upload_tasks import _stage_generating, _stage_ocr


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _make_upload(db, deck_id=None, **kwargs) -> Upload:
    defaults = dict(filename="test.pdf", file_type="pdf", kind="single", stage="ocr", status="processing")
    defaults.update(kwargs)
    upload = Upload(deck_id=deck_id, **defaults)
    db.add(upload)
    await db.flush()
    return upload


# ---------------------------------------------------------------------------
# _stage_ocr: text-layer replacement-char guard
# ---------------------------------------------------------------------------

class TestStageOcrReplacementCharGuard:
    @pytest.mark.asyncio
    async def test_replacement_chars_fall_back_to_ocr_clean_page_uses_text_layer(self, db, tmp_path):
        settings = Settings(media_dir=str(tmp_path))
        upload = await _make_upload(db)
        await db.commit()

        upload_dir = tmp_path / "uploads" / str(upload.id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / upload.filename).write_bytes(b"%PDF-1.4 dummy")

        corrupted_page = "ก" * 50 + "�"
        clean_page = "ก" * 50

        mock_ocr = AsyncMock(return_value=OcrResult(text="ocr text", engine_used="easy", confidence=0.9))

        with (
            patch("src.tasks.upload_tasks.extract_pdf_text_layer", return_value=[corrupted_page, clean_page]),
            patch(
                "src.tasks.upload_tasks.prepare_file_for_ocr",
                return_value=[(b"img0", "image/jpeg"), (b"img1", "image/jpeg")],
            ),
            patch("src.tasks.upload_tasks.run_ocr_pipeline", new=mock_ocr),
        ):
            await _stage_ocr(db, upload, settings)

        pages = list(
            (await db.execute(
                select(UploadPage).where(UploadPage.upload_id == upload.id).order_by(UploadPage.page_index)
            )).scalars().all()
        )
        assert len(pages) == 2
        assert pages[0].engine_used == "easy"  # corrupted text layer -> OCR fallback
        assert pages[1].engine_used == "pdf_text"  # clean text layer -> used as-is
        mock_ocr.assert_awaited_once()


# ---------------------------------------------------------------------------
# _stage_generating: repair before generate_all(), flag on unverified repair
# ---------------------------------------------------------------------------

class TestStageGeneratingIntegrityGuard:
    @pytest_asyncio.fixture
    async def upload_with_deck(self, db):
        deck = Deck(name="Test Deck")
        db.add(deck)
        await db.flush()
        upload = await _make_upload(db, deck_id=deck.id, stage="generating", raw_text="raw text")
        await db.commit()
        return upload

    @pytest.mark.asyncio
    async def test_validated_repair_stores_repaired_card_with_no_flag(self, db, upload_with_deck):
        cards_data = [{
            "thai": "ลำ�ไส้", "romanization": "lam � sâi", "english": "intestines",
            "example_thai": None, "example_english": None, "card_type": "vocab",
        }]
        with patch("src.tasks.upload_tasks._generate_cards_chunked", new=AsyncMock(return_value=cards_data)):
            await _stage_generating(db, upload_with_deck)

        cards = list(
            (await db.execute(select(Card).where(Card.source_upload_id == upload_with_deck.id))).scalars().all()
        )
        assert len(cards) == 1
        card = cards[0]
        assert card.thai == "ลำไส้"
        assert card.romanization_source == "lam sâi"
        assert card.romanization_paiboon

        flags = list((await db.execute(select(CardFlag))).scalars().all())
        assert flags == []

    @pytest.mark.asyncio
    async def test_unverifiable_repair_creates_exactly_one_other_flag(self, db, upload_with_deck):
        bogus = "มกฉ�ฬฒ"
        cards_data = [{
            "thai": bogus, "romanization": None, "english": "nonsense",
            "example_thai": None, "example_english": None, "card_type": "vocab",
        }]
        with patch("src.tasks.upload_tasks._generate_cards_chunked", new=AsyncMock(return_value=cards_data)):
            await _stage_generating(db, upload_with_deck)

        cards = list(
            (await db.execute(select(Card).where(Card.source_upload_id == upload_with_deck.id))).scalars().all()
        )
        assert len(cards) == 1
        assert "�" not in cards[0].thai

        flags = list((await db.execute(select(CardFlag))).scalars().all())
        assert len(flags) == 1
        assert flags[0].target == "other"
        assert flags[0].card_id == cards[0].id
        import json
        flagged_value = json.loads(flags[0].flagged_value)
        assert flagged_value["reason"] == "invalid_chars_unverified_repair"
        assert flagged_value["field"] == "thai"
