"""
Tests for src/utils/card_overrides.py — the per-user override overlay
resolver (mirrors romanization.py's resolve_effective(values, prefs)).

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_card_overrides.py -v
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base, Deck, Card
from src.db.models.card_override import CardOverride
from src.db.models.card_flag import CardFlag
from src.utils.card_overrides import (
    apply_overrides,
    load_overrides,
    load_open_flag_targets,
    upsert_override,
    delete_override,
)


# ---------------------------------------------------------------------------
# apply_overrides() — pure, no I/O
# ---------------------------------------------------------------------------

class TestApplyOverrides:
    def test_no_override_dict_is_unchanged(self):
        card_dict = {"id": 1, "english": "cat", "compound_breakdown": None, "is_compound": None}
        result = apply_overrides(card_dict, {})
        assert result == card_dict

    def test_translation_override_changes_english_and_sets_source(self):
        card_dict = {"id": 1, "english": "cat"}
        result = apply_overrides(card_dict, {"translation": {"english": "kitten", "from_candidate": True}})
        assert result["english"] == "kitten"
        assert result["english_source"] == "user"
        # original dict untouched
        assert card_dict["english"] == "cat"
        assert "english_source" not in card_dict

    def test_compound_suppressed_nulls_breakdown_leaves_is_compound_true(self):
        card_dict = {
            "id": 1,
            "compound_breakdown": [{"thai": "น้ำ", "gloss": "water"}],
            "is_compound": True,
        }
        result = apply_overrides(card_dict, {"compound": {"suppressed": True}})
        assert result["compound_breakdown"] is None
        assert result["compound_suppressed"] is True
        assert result["is_compound"] is True

    def test_compound_parts_replaces_array_wholesale(self):
        card_dict = {
            "id": 1,
            "compound_breakdown": [{"thai": "น้ำ", "gloss": "water"}],
            "is_compound": True,
        }
        new_parts = [
            {"thai": "น้ำแข็ง", "romanization": "nam khaeng", "gloss": "ice", "gloss_source": "card"},
        ]
        result = apply_overrides(card_dict, {"compound": {"parts": new_parts}})
        assert result["compound_breakdown"] == new_parts
        assert result["compound_breakdown_source"] == "user"
        assert result["is_compound"] is True

    def test_both_translation_and_compound_apply_together(self):
        card_dict = {"id": 1, "english": "cat", "compound_breakdown": None, "is_compound": False}
        result = apply_overrides(
            card_dict,
            {
                "translation": {"english": "kitten"},
                "compound": {"suppressed": True},
            },
        )
        assert result["english"] == "kitten"
        assert result["compound_breakdown"] is None
        assert result["compound_suppressed"] is True


# ---------------------------------------------------------------------------
# load_overrides / load_open_flag_targets / upsert_override / delete_override
# — DB-backed, real in-memory sqlite
# ---------------------------------------------------------------------------

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


async def _make_card(db, thai="แมว", english="cat"):
    deck = Deck(name="Test Deck")
    db.add(deck)
    await db.flush()
    card = Card(deck_id=deck.id, thai=thai, english=english, card_type="vocab")
    db.add(card)
    await db.flush()
    return card


class TestLoadOverrides:
    @pytest.mark.asyncio
    async def test_empty_card_ids_returns_empty_dict(self, db):
        assert await load_overrides(db, [], user_id=1) == {}

    @pytest.mark.asyncio
    async def test_batches_multiple_cards_in_one_call(self, db):
        card_a = await _make_card(db, "แมว", "cat")
        card_b = await _make_card(db, "หมา", "dog")
        await upsert_override(db, 1, card_a.id, "translation", {"english": "kitten"})
        await upsert_override(db, 1, card_b.id, "compound", {"suppressed": True})
        await db.commit()

        result = await load_overrides(db, [card_a.id, card_b.id], user_id=1)
        assert result[card_a.id] == {"translation": {"english": "kitten"}}
        assert result[card_b.id] == {"compound": {"suppressed": True}}

    @pytest.mark.asyncio
    async def test_scoped_to_user_id(self, db):
        card = await _make_card(db)
        await upsert_override(db, 1, card.id, "translation", {"english": "kitten"})
        await db.commit()

        assert await load_overrides(db, [card.id], user_id=2) == {}


class TestUpsertOverride:
    @pytest.mark.asyncio
    async def test_second_upsert_updates_not_duplicates(self, db):
        card = await _make_card(db)
        await upsert_override(db, 1, card.id, "translation", {"english": "kitten"})
        await upsert_override(db, 1, card.id, "translation", {"english": "kitty"})
        await db.commit()

        result = await load_overrides(db, [card.id], user_id=1)
        assert result[card.id]["translation"]["english"] == "kitty"

        from sqlalchemy import select, func
        count = await db.scalar(select(func.count()).select_from(CardOverride))
        assert count == 1


class TestDeleteOverride:
    @pytest.mark.asyncio
    async def test_delete_then_load_returns_nothing(self, db):
        card = await _make_card(db)
        await upsert_override(db, 1, card.id, "translation", {"english": "kitten"})
        await db.commit()

        deleted = await delete_override(db, 1, card.id, "translation")
        await db.commit()
        assert deleted is True

        assert await load_overrides(db, [card.id], user_id=1) == {}

    @pytest.mark.asyncio
    async def test_delete_when_nothing_exists_is_a_noop(self, db):
        card = await _make_card(db)
        deleted = await delete_override(db, 1, card.id, "translation")
        assert deleted is False


class TestLoadOpenFlagTargets:
    @pytest.mark.asyncio
    async def test_only_open_flags_are_returned(self, db):
        card = await _make_card(db)
        db.add(CardFlag(user_id=1, card_id=card.id, target="translation", status="open"))
        db.add(CardFlag(user_id=1, card_id=card.id, target="compound", status="resolved"))
        await db.flush()
        await db.commit()

        result = await load_open_flag_targets(db, [card.id], user_id=1)
        assert result[card.id] == ["translation"]
