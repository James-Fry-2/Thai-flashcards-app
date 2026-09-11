"""
Tests for the new candidate-generation surface added to src/utils/compound.py
for the user-flags-overrides feature: enumerate_segmentations() and
gloss_candidates(), plus the two GET .../candidates API endpoints.

tests/test_compound.py is the contract test for decompose()/resolve_glosses()/
pick_best_gloss()/select_gloss_by_level() and is deliberately left unmodified
by this feature — see that file for the ladder-selection behaviour this one
must stay consistent with.

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_compound_candidates.py -v
"""
import json

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base, Deck, Card
from src.db.models.lexicon import Lexicon
from src.api.deps import get_db


# ---------------------------------------------------------------------------
# enumerate_segmentations() — pure / deterministic, real corpus
# ---------------------------------------------------------------------------

class TestEnumerateSegmentations:
    def test_includes_two_part_split_and_whole_word(self):
        from src.utils.compound import enumerate_segmentations

        segmentations = enumerate_segmentations("น้ำแข็ง", limit=8)
        assert ["น้ำ", "แข็ง"] in segmentations
        # น้ำแข็ง is itself a dictionary entry -> the "not a compound" option
        assert ["น้ำแข็ง"] in segmentations

    def test_whole_word_option_sorts_first(self):
        """Ascending part count means the 1-part whole-word option, when it
        exists, is always the most-preferred candidate."""
        from src.utils.compound import enumerate_segmentations

        segmentations = enumerate_segmentations("น้ำแข็ง", limit=8)
        assert segmentations[0] == ["น้ำแข็ง"]

    def test_respects_limit(self):
        from src.utils.compound import enumerate_segmentations

        segmentations = enumerate_segmentations("น้ำแข็ง", limit=1)
        assert len(segmentations) <= 1

    def test_empty_string_returns_empty_list(self):
        from src.utils.compound import enumerate_segmentations

        assert enumerate_segmentations("") == []

    def test_non_thai_returns_empty_list(self):
        from src.utils.compound import enumerate_segmentations

        assert enumerate_segmentations("hello") == []

    def test_never_raises_on_corpus_failure(self):
        from src.utils.compound import enumerate_segmentations

        with patch("src.utils.compound._thai_word_set", side_effect=RuntimeError("boom")):
            assert enumerate_segmentations("น้ำแข็ง") == []

    def test_decompose_unchanged_by_the_refactor(self):
        """decompose() must return exactly what it returned before this
        feature — same cases as tests/test_compound.py's TestDecompose."""
        from src.utils.compound import decompose

        assert decompose("น้ำแข็ง") is not None and "".join(decompose("น้ำแข็ง")) == "น้ำแข็ง"
        assert decompose("รถไฟ") is not None and "".join(decompose("รถไฟ")) == "รถไฟ"
        assert decompose("คอมพิวเตอร์") is None
        assert decompose("") is None
        assert decompose("hello") is None


# ---------------------------------------------------------------------------
# gloss_candidates() — superset of resolve_glosses()'s single selection
# ---------------------------------------------------------------------------

class TestGlossCandidates:
    @pytest.mark.asyncio
    async def test_superset_of_resolve_glosses_selection(self):
        """Regression fixture from the real รัก entry (see test_compound.py):
        gloss_candidates must expose the discarded senses, and the selection
        resolve_glosses()/pick_best_gloss() makes must be gloss_candidates'
        first entry."""
        from src.utils.compound import gloss_candidates, resolve_glosses

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=None)  # no own card

        rak_senses = [
            {"english": e, "level": None, "pos": None} for e in (
                "Calotropis gigantea", "Crown flower", "lacquer", "love",
                "be fond of", "be keen on", "cherish", "adore", "like",
            )
        ]
        with patch("src.db.services.lexicon_service.lookup_ranked", new=AsyncMock(return_value=rak_senses)):
            candidates = await gloss_candidates(mock_db, "รัก")
            resolved = await resolve_glosses(mock_db, ["รัก"])

        selected_gloss = resolved[0]["gloss"]
        selected_source = resolved[0]["gloss_source"]

        assert selected_gloss in ("love", "like")
        assert candidates[0]["gloss"] == selected_gloss
        assert candidates[0]["source"] == selected_source
        # the discarded senses are visible, not just the winner
        candidate_glosses = {c["gloss"] for c in candidates}
        assert {"love", "like"} & candidate_glosses
        assert "Calotropis gigantea" not in candidate_glosses  # binomial still dropped

    @pytest.mark.asyncio
    async def test_card_gloss_wins_and_is_first(self):
        from src.utils.compound import gloss_candidates

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value="water")

        with patch("src.utils.compound._wordnet_gloss", return_value=("liquid", "lexicon")):
            candidates = await gloss_candidates(mock_db, "น้ำ")

        assert candidates[0] == {"gloss": "water", "source": "card"}

    @pytest.mark.asyncio
    async def test_capped_at_eight(self):
        from src.utils.compound import gloss_candidates

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=None)

        many_senses = [{"english": f"sense{i}", "level": None, "pos": None} for i in range(20)]
        with patch("src.db.services.lexicon_service.lookup_ranked", new=AsyncMock(return_value=many_senses)):
            candidates = await gloss_candidates(mock_db, "คำ")

        assert len(candidates) <= 8

    @pytest.mark.asyncio
    async def test_empty_when_nothing_resolves(self):
        from src.utils.compound import gloss_candidates

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=None)

        with patch("src.utils.compound._wordnet_gloss", return_value=(None, None)):
            candidates = await gloss_candidates(mock_db, "xyz")

        assert candidates == []


# ---------------------------------------------------------------------------
# API: candidate endpoints don't depend on stored, potentially-stale columns
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client():
    from src.main import app

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, factory

    app.dependency_overrides.clear()
    await engine.dispose()


class TestTranslationCandidatesEndpoint:
    @pytest.mark.asyncio
    async def test_returns_lexicon_candidates_for_an_ok_status_card(self, client):
        """translation_status='ok' cards never populate translation_candidates
        (that column is only written by check_translation() when it flags a
        card) — the endpoint must hit the lexicon fresh, not read the stored
        column, or this case would incorrectly return []."""
        ac, factory = client
        async with factory() as db:
            deck = Deck(name="Test Deck")
            db.add(deck)
            await db.flush()
            db.add(Lexicon(thai="รถไฟ", english="train", source="volubilis"))
            db.add(Lexicon(thai="รถไฟ", english="railway", source="volubilis"))
            card = Card(
                deck_id=deck.id, thai="รถไฟ", english="railway", card_type="vocab",
                translation_status="ok", translation_candidates=None,
            )
            db.add(card)
            await db.commit()
            card_id = card.id

        resp = await ac.get(f"/api/cards/{card_id}/translation-candidates")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data["candidates"]) == {"train", "railway"}
        assert data["allow_free_text"] is True
