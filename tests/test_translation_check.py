"""
Tests for src/utils/translation_check.py, and the resolve-translation flow
(POST /cards/{id}/resolve-translation) exercised through the real ASGI app.

As of the user-flags-overrides feature, action='correct' upserts a
`card_override` row rather than writing `cards.english` directly — see
src/utils/card_overrides.py. tests/test_flags_api.py also covers this route
(TestScopeIsolation.test_resolve_translation_correct_leaves_card_row_unmodified);
the tests below are the translation-check-focused counterpart.

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_translation_check.py -v
"""
import json

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import AsyncMock, MagicMock, patch

from src.db.models import Base, Deck, Card
from src.db.models.card_override import CardOverride
from src.api.deps import get_db


# ---------------------------------------------------------------------------
# check_translation() — the flagging decision
# ---------------------------------------------------------------------------

class TestCheckTranslation:

    @pytest.mark.asyncio
    async def test_unknown_thai_is_unverified_never_flagged(self):
        """No lexicon rows for the Thai word -> unverified, not flagged."""
        from src.utils.translation_check import check_translation

        mock_db = AsyncMock()
        with patch("src.db.services.lexicon_service.lookup", new=AsyncMock(return_value=[])):
            status, candidates = await check_translation(mock_db, "แปลกๆ", "something odd")

        assert status == "unverified"
        assert candidates is None

    @pytest.mark.asyncio
    async def test_matching_translation_is_ok(self):
        from src.utils.translation_check import check_translation

        mock_db = AsyncMock()
        with patch("src.db.services.lexicon_service.lookup", new=AsyncMock(return_value=["railway"])):
            status, candidates = await check_translation(mock_db, "รถไฟ", "railway")

        assert status == "ok"
        assert candidates is None

    @pytest.mark.asyncio
    async def test_clear_mismatch_is_flagged_with_candidates(self):
        """Lexicon has entries, but the material english shares no content token -> flagged."""
        from src.utils.translation_check import check_translation

        mock_db = AsyncMock()
        with patch(
            "src.db.services.lexicon_service.lookup",
            new=AsyncMock(return_value=["train", "railway"]),
        ):
            status, candidates = await check_translation(mock_db, "รถไฟ", "bicycle")

        assert status == "flagged"
        assert candidates == ["train", "railway"]

    @pytest.mark.asyncio
    async def test_phrasing_difference_shares_token_is_ok(self):
        """"railway" vs "railway line" -> shared content token, no false positive."""
        from src.utils.translation_check import check_translation

        mock_db = AsyncMock()
        with patch("src.db.services.lexicon_service.lookup", new=AsyncMock(return_value=["railway"])):
            status, candidates = await check_translation(mock_db, "รถไฟ", "railway line")

        assert status == "ok"
        assert candidates is None

    @pytest.mark.asyncio
    async def test_stopwords_and_punctuation_ignored(self):
        from src.utils.translation_check import check_translation

        mock_db = AsyncMock()
        with patch("src.db.services.lexicon_service.lookup", new=AsyncMock(return_value=["a train"])):
            status, _ = await check_translation(mock_db, "รถไฟ", "the train.")

        assert status == "ok"

    @pytest.mark.asyncio
    async def test_candidates_capped_at_five(self):
        from src.utils.translation_check import check_translation

        mock_db = AsyncMock()
        many = [f"sense{i}" for i in range(8)]
        with patch("src.db.services.lexicon_service.lookup", new=AsyncMock(return_value=many)):
            status, candidates = await check_translation(mock_db, "คำ", "unrelated")

        assert status == "flagged"
        assert candidates == many[:5]


class TestContentTokens:

    def test_lowercases_and_strips_punctuation(self):
        from src.utils.translation_check import _content_tokens
        assert _content_tokens("Railway, Line!") == {"railway", "line"}

    def test_drops_stopwords(self):
        from src.utils.translation_check import _content_tokens
        assert _content_tokens("a train") == {"train"}
        assert _content_tokens("the railway of thailand") == {"railway", "thailand"}


# ---------------------------------------------------------------------------
# resolve-translation flow — keep vs. correct, via POST /cards/{id}/resolve-
# translation (the real route). 'correct' upserts an override; it must never
# touch cards.english (see src/utils/card_overrides.py).
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


async def _seed_flagged_card(factory, thai="รถไฟ", english="bicycle"):
    async with factory() as db:
        deck = Deck(name="Test Deck")
        db.add(deck)
        await db.flush()
        card = Card(
            deck_id=deck.id, thai=thai, english=english, card_type="vocab",
            translation_status="flagged", translation_candidates=json.dumps(["train"]),
        )
        db.add(card)
        await db.commit()
        return card.id


class TestResolveTranslationFlow:

    @pytest.mark.asyncio
    async def test_keep_confirms_status_without_changing_english(self, client):
        ac, factory = client
        card_id = await _seed_flagged_card(factory, english="bicycle")

        resp = await ac.post(f"/api/cards/{card_id}/resolve-translation", json={"action": "keep"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["translation_status"] == "confirmed"
        assert data["translation_candidates"] is None
        assert data["english"] == "bicycle"  # material value untouched

        async with factory() as db:
            override = await db.scalar(select(CardOverride).where(CardOverride.card_id == card_id))
            assert override is None  # 'keep' is not a content edit, no override row

    @pytest.mark.asyncio
    async def test_correct_writes_an_override_and_leaves_cards_english_unmodified(self, client):
        ac, factory = client
        card_id = await _seed_flagged_card(factory, english="bicycle")

        resp = await ac.post(
            f"/api/cards/{card_id}/resolve-translation",
            json={"action": "correct", "english": "train"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["english"] == "train"  # effective (overridden) value
        assert data["translation_status"] == "confirmed"
        assert data["translation_candidates"] is None

        async with factory() as db:
            card = await db.get(Card, card_id)
            assert card.english == "bicycle"  # material value in the row, untouched

            override = await db.scalar(select(CardOverride).where(CardOverride.card_id == card_id))
            assert override is not None
            assert override.target == "translation"
            assert json.loads(override.payload)["english"] == "train"

    @pytest.mark.asyncio
    async def test_correct_without_english_is_422(self, client):
        ac, factory = client
        card_id = await _seed_flagged_card(factory)

        resp = await ac.post(f"/api/cards/{card_id}/resolve-translation", json={"action": "correct"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# On-demand LLM second opinion — src/llm/prompts/translation_verify.py and
# src/db/services/translation_verify_service.py
#
# Prompt-parsing tests are pure (no db, no network). The service test below
# asserts it never constructs a provider unless translation_status=='flagged'.
# ---------------------------------------------------------------------------

class TestParseTranslationVerifyResponse:

    @pytest.mark.parametrize("verdict", ["likely_error", "likely_ok", "unsure"])
    def test_valid_verdicts_parse(self, verdict):
        from src.llm.prompts.translation_verify import parse_translation_verify_response

        raw = f'{{"verdict": "{verdict}", "reason": "because reasons"}}'
        parsed_verdict, reason = parse_translation_verify_response(raw)

        assert parsed_verdict == verdict
        assert reason == "because reasons"

    def test_junk_returns_none_none(self):
        from src.llm.prompts.translation_verify import parse_translation_verify_response

        parsed_verdict, reason = parse_translation_verify_response("not json at all {{{")

        assert parsed_verdict is None
        assert reason is None

    def test_invalid_verdict_value_becomes_none(self):
        from src.llm.prompts.translation_verify import parse_translation_verify_response

        raw = '{"verdict": "maybe", "reason": "shrug"}'
        parsed_verdict, reason = parse_translation_verify_response(raw)

        assert parsed_verdict is None
        assert reason == "shrug"

    def test_markdown_fenced_json_is_parsed(self):
        from src.llm.prompts.translation_verify import parse_translation_verify_response

        raw = '```json\n{"verdict": "likely_ok", "reason": "valid paraphrase"}\n```'
        parsed_verdict, reason = parse_translation_verify_response(raw)

        assert parsed_verdict == "likely_ok"
        assert reason == "valid paraphrase"

    def test_missing_reason_is_none(self):
        from src.llm.prompts.translation_verify import parse_translation_verify_response

        raw = '{"verdict": "unsure"}'
        parsed_verdict, reason = parse_translation_verify_response(raw)

        assert parsed_verdict == "unsure"
        assert reason is None


class TestVerifyTranslationService:

    @pytest.mark.asyncio
    async def test_not_flagged_returns_early_without_provider(self):
        from src.db.services import translation_verify_service

        card = MagicMock()
        card.translation_status = "unverified"
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=card)

        with patch("src.db.services.translation_verify_service.get_provider") as mock_get_provider:
            result = await translation_verify_service.verify_translation(mock_db, 1)

        assert result == {"status": "not_flagged"}
        mock_get_provider.assert_not_called()

    @pytest.mark.asyncio
    async def test_card_not_found_returns_not_flagged(self):
        from src.db.services import translation_verify_service

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        with patch("src.db.services.translation_verify_service.get_provider") as mock_get_provider:
            result = await translation_verify_service.verify_translation(mock_db, 999)

        assert result == {"status": "not_flagged"}
        mock_get_provider.assert_not_called()

    @pytest.mark.asyncio
    async def test_flagged_card_calls_provider_and_returns_verdict(self):
        from src.db.services import translation_verify_service
        from src.llm.base import LLMResponse

        card = MagicMock()
        card.translation_status = "flagged"
        card.thai = "รถไฟ"
        card.romanization = "rot fai"
        card.english = "bicycle"
        card.translation_candidates = json.dumps(["train", "railway"])
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=card)

        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(return_value=LLMResponse(
            text='{"verdict": "likely_error", "reason": "bicycle is not a sense of train"}',
            input_tokens=240,
            output_tokens=18,
            model="claude-haiku-4-5-20251001",
        ))

        with patch("src.db.services.translation_verify_service.get_provider", return_value=mock_provider):
            result = await translation_verify_service.verify_translation(mock_db, 1)

        assert result["status"] == "checked"
        assert result["verdict"] == "likely_error"
        assert result["reason"] == "bicycle is not a sense of train"
