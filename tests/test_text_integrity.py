"""
Tests for src/utils/text_integrity.py (pure) and
src/db/services/text_integrity_service.py (lexicon-validated Thai repair).

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_text_integrity.py -v
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.db.models import Base
from src.db.services.text_integrity_service import repair_thai_field
from src.utils.text_integrity import (
    count_replacement_chars,
    find_invalid_chars,
    normalise_text,
    repair_non_thai_field,
)


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


# ---------------------------------------------------------------------------
# find_invalid_chars
# ---------------------------------------------------------------------------

class TestFindInvalidChars:
    def test_reports_pua_and_control_chars(self):
        text = "ab\x01c"
        indices = [i for i, _ in find_invalid_chars(text)]
        assert indices == [1, 3]

    def test_does_not_flag_latin_newline_or_tab(self):
        assert find_invalid_chars("Hello\n\tWorld") == []

    def test_flags_replacement_character(self):
        indices = [i for i, _ in find_invalid_chars("a�b")]
        assert indices == [1]


# ---------------------------------------------------------------------------
# normalise_text
# ---------------------------------------------------------------------------

class TestNormaliseText:
    def test_recomposes_decomposed_sara_am_with_tone_mark(self):
        normalized, repairs = normalise_text("นํ้า")
        assert normalized == "น้ำ"
        assert repairs

    def test_recomposes_decomposed_sara_am_without_tone_mark(self):
        normalized, repairs = normalise_text("ดํา")
        assert normalized == "ดำ"
        assert repairs

    def test_strips_zero_width_characters(self):
        normalized, repairs = normalise_text("ทำ​งาน")
        assert normalized == "ทำงาน"
        assert repairs

    def test_clean_thai_unchanged(self):
        normalized, repairs = normalise_text("แมว")
        assert normalized == "แมว"
        assert repairs == []

    def test_clean_english_unchanged(self):
        normalized, repairs = normalise_text("hello world")
        assert normalized == "hello world"
        assert repairs == []

    def test_idempotent(self):
        text = "นํ้า​ทำ"
        once, _ = normalise_text(text)
        twice, repairs_twice = normalise_text(once)
        assert once == twice
        assert repairs_twice == []


# ---------------------------------------------------------------------------
# repair_non_thai_field (decision 6 — no validation)
# ---------------------------------------------------------------------------

class TestRepairNonThaiField:
    def test_clean_text_unchanged(self):
        result = repair_non_thai_field("hello world")
        assert result.text == "hello world"
        assert result.changed is False
        assert result.invalid_remaining == []

    def test_removes_replacement_char_and_collapses_whitespace(self):
        result = repair_non_thai_field("lam � sâi")
        assert "�" not in result.text
        assert "  " not in result.text
        assert result.changed is True
        assert result.text == "lam sâi"


# ---------------------------------------------------------------------------
# count_replacement_chars
# ---------------------------------------------------------------------------

class TestCountReplacementChars:
    def test_counts_occurrences(self):
        assert count_replacement_chars("a�b�") == 2
        assert count_replacement_chars("clean") == 0


# ---------------------------------------------------------------------------
# repair_thai_field (decision 5 — lexicon-validated repair)
# ---------------------------------------------------------------------------

class TestRepairThaiField:
    @pytest.mark.asyncio
    async def test_intestines_example_repairs_and_validates(self, db):
        result, validated = await repair_thai_field(db, "ลำ�ไส้", "thai")
        assert result.text == "ลำไส้"
        assert result.changed is True
        assert validated is True

    @pytest.mark.asyncio
    async def test_unrecognisable_word_repairs_but_is_not_validated(self, db):
        bogus = "มกฉ�ฬฒ"
        result, validated = await repair_thai_field(db, bogus, "thai")
        assert "�" not in result.text
        assert result.changed is True
        assert validated is False

    @pytest.mark.asyncio
    async def test_pua_character_is_left_unrepaired(self, db):
        text = "กข"
        result, validated = await repair_thai_field(db, text, "thai")
        assert result.invalid_remaining
        assert validated is False
        # Decision 7: PUA/control invalid chars are not stripped, only flagged.
        assert "" in result.text

    @pytest.mark.asyncio
    async def test_clean_thai_is_validated_with_no_change(self, db):
        result, validated = await repair_thai_field(db, "แมว", "thai")
        assert result.changed is False
        assert validated is True

    @pytest.mark.asyncio
    async def test_example_thai_validates_every_thai_token(self, db):
        # "ทำงาน" is a real word both sides of the FFFD once removed.
        result, validated = await repair_thai_field(db, "ทำ�งาน", "example_thai")
        assert result.text == "ทำงาน"
        assert validated is True
