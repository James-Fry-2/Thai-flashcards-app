"""
Tests for src/db/services/distractor_service.py — the th_to_en multiple-choice
quiz's distractor selection and validity guard.

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_distractor_service.py -v
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base, Deck, Card
from src.db.models.card_link import CardLink
from src.db.services.distractor_service import build_option_slate, is_valid_distractor


# ---------------------------------------------------------------------------
# is_valid_distractor — pure function, no db needed
# ---------------------------------------------------------------------------

def _card(id, thai, english):
    return Card(id=id, deck_id=1, thai=thai, english=english, card_type="vocab")


class TestIsValidDistractor:
    def test_rejects_same_card(self):
        c = _card(1, "แมว", "cat")
        ok, reason = is_valid_distractor(c, c)
        assert ok is False

    def test_rejects_identical_gloss(self):
        target = _card(1, "แมว", "cat")
        candidate = _card(2, "เหมียว", "cat")
        ok, reason = is_valid_distractor(target, candidate)
        assert ok is False
        assert reason == "identical gloss"

    def test_rejects_to_eat_eat_pair(self):
        target = _card(1, "กิน", "to eat")
        candidate = _card(2, "ทาน", "eat")
        ok, reason = is_valid_distractor(target, candidate)
        assert ok is False
        assert reason == "identical gloss"

    def test_rejects_shared_content_word(self):
        target = _card(1, "บ้าน", "house")
        candidate = _card(2, "บ้านพัก", "guest house")
        ok, reason = is_valid_distractor(target, candidate)
        assert ok is False
        assert reason == "shared content word"

    def test_rejects_identical_thai(self):
        target = _card(1, "แมว", "cat")
        candidate = _card(2, "แมว", "kitty")
        ok, reason = is_valid_distractor(target, candidate)
        assert ok is False
        assert reason == "identical thai"

    def test_accepts_unrelated_gloss(self):
        target = _card(1, "แมว", "cat")
        candidate = _card(2, "หนังสือ", "book")
        ok, reason = is_valid_distractor(target, candidate)
        assert ok is True
        assert reason is None


# ---------------------------------------------------------------------------
# build_option_slate — needs a real (in-memory) async db
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


async def _make_deck(db, name="Test Deck"):
    deck = Deck(name=name)
    db.add(deck)
    await db.flush()
    return deck


async def _make_card(db, deck_id, thai, english, **kwargs):
    card = Card(deck_id=deck_id, thai=thai, english=english, card_type=kwargs.pop("card_type", "vocab"), **kwargs)
    db.add(card)
    await db.flush()
    return card


_FILLER_WORDS = [
    "book", "car", "tree", "river", "mountain", "chair", "table", "window",
    "door", "cloud", "stone", "flower", "bridge", "forest", "island",
    "desert", "valley", "garden", "kitchen", "bicycle", "airplane",
    "umbrella", "candle", "mirror", "pillow", "blanket", "hammer",
    "ladder", "bottle", "basket",
]


async def _make_filler_cards(db, deck_id, n):
    """A pool of mutually-unrelated, mutually-valid cards for backfill/random
    slots — distinct single-word glosses so they're also valid against
    *each other*, not just against whatever card is the target."""
    assert n <= len(_FILLER_WORDS), "add more words to _FILLER_WORDS"
    cards = []
    for i in range(n):
        c = await _make_card(db, deck_id, f"เติม{i}", _FILLER_WORDS[i])
        cards.append(c)
    return cards


class TestBuildOptionSlateComposition:
    @pytest.mark.asyncio
    async def test_never_returns_target_twice(self, db):
        deck = await _make_deck(db)
        target = await _make_card(db, deck.id, "แมว", "cat")
        await _make_filler_cards(db, deck.id, 6)

        slate = await build_option_slate(db, target.id, n_options=4)
        card_ids = [o["card_id"] for o in slate]
        assert card_ids.count(target.id) == 1
        assert len(card_ids) == len(set(card_ids))

    @pytest.mark.asyncio
    async def test_uses_orthographic_confusable_link(self, db):
        deck = await _make_deck(db)
        target = await _make_card(db, deck.id, "เสือ", "tiger")
        confusable = await _make_card(db, deck.id, "เสื้อ", "shirt")
        await _make_filler_cards(db, deck.id, 6)

        db.add(CardLink(
            from_card_id=target.id, to_card_id=confusable.id,
            link_type="confusable", note="orthographic",
        ))
        await db.flush()

        slate = await build_option_slate(db, target.id, n_options=4)
        sources = {o["card_id"]: o["source"] for o in slate}
        assert sources.get(confusable.id) == "orthographic"

    @pytest.mark.asyncio
    async def test_uses_phonetic_confusable_link(self, db):
        deck = await _make_deck(db)
        target = await _make_card(db, deck.id, "สวย", "pretty")
        confusable = await _make_card(db, deck.id, "ซวย", "unlucky")
        await _make_filler_cards(db, deck.id, 6)

        db.add(CardLink(
            from_card_id=target.id, to_card_id=confusable.id,
            link_type="confusable", note="phonetic",
        ))
        await db.flush()

        slate = await build_option_slate(db, target.id, n_options=4)
        sources = {o["card_id"]: o["source"] for o in slate}
        assert sources.get(confusable.id) == "phonetic"

    @pytest.mark.asyncio
    async def test_one_directional_confusable_link_still_found(self, db):
        """card_links is symmetric for 'confusable' per SYMMETRIC_LINK_TYPES,
        but a partial detection run could leave one-directional rows — the
        from_card_id-only query must still work in that case."""
        deck = await _make_deck(db)
        target = await _make_card(db, deck.id, "เสือ", "tiger")
        confusable = await _make_card(db, deck.id, "เสื้อ", "shirt")
        await _make_filler_cards(db, deck.id, 6)

        # Only the target -> confusable direction exists (no reverse row).
        db.add(CardLink(
            from_card_id=target.id, to_card_id=confusable.id,
            link_type="confusable", note="orthographic",
        ))
        await db.flush()

        slate = await build_option_slate(db, target.id, n_options=4)
        card_ids = {o["card_id"] for o in slate}
        assert confusable.id in card_ids

    @pytest.mark.asyncio
    async def test_excludes_soft_deleted_decks_from_candidate_pool(self, db):
        deck = await _make_deck(db)
        deleted_deck = await _make_deck(db, name="Deleted")
        from datetime import datetime, timezone
        deleted_deck.deleted_at = datetime.now(timezone.utc)
        await db.flush()

        target = await _make_card(db, deck.id, "แมว", "cat")
        # Only candidate lives in a soft-deleted deck — pool should be empty.
        await _make_card(db, deleted_deck.id, "หนังสือ", "book")

        slate = await build_option_slate(db, target.id, n_options=4)
        assert len(slate) == 1  # target only, thin pool


class TestBuildOptionSlateThinPool:
    @pytest.mark.asyncio
    async def test_returns_fewer_than_n_options_when_pool_thin(self, db):
        deck = await _make_deck(db)
        target = await _make_card(db, deck.id, "แมว", "cat")
        await _make_filler_cards(db, deck.id, 2)  # only 2 valid distractors available

        slate = await build_option_slate(db, target.id, n_options=4)
        assert len(slate) == 3  # target + 2, not 4


class TestBuildOptionSlateRandomization:
    @pytest.mark.asyncio
    async def test_target_position_distribution_not_degenerate(self, db):
        deck = await _make_deck(db)
        target = await _make_card(db, deck.id, "แมว", "cat")
        await _make_filler_cards(db, deck.id, 20)

        positions = []
        for _ in range(200):
            slate = await build_option_slate(db, target.id, n_options=4)
            target_option = next(o for o in slate if o["card_id"] == target.id)
            positions.append(target_option["position"])

        assert set(positions) == {0, 1, 2, 3}
        for pos in range(4):
            assert positions.count(pos) <= 80  # <= 40% of 200

    @pytest.mark.asyncio
    async def test_no_caching_distractor_sets_vary(self, db):
        deck = await _make_deck(db)
        target = await _make_card(db, deck.id, "แมว", "cat")
        await _make_filler_cards(db, deck.id, 20)

        distractor_sets = set()
        for _ in range(20):
            slate = await build_option_slate(db, target.id, n_options=4)
            distractors = frozenset(o["card_id"] for o in slate if o["card_id"] != target.id)
            distractor_sets.add(distractors)

        assert len(distractor_sets) > 1
