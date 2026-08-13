"""
Tests for src/utils/translation_check.py, and the resolve-translation flow
(POST /cards/{id}/resolve-translation) as expressed through
card_service.update_card.

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_translation_check.py -v
"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


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
# resolve-translation flow — keep vs. correct, via card_service.update_card
# (the route just forwards to update_card with these kwargs).
# ---------------------------------------------------------------------------

class TestResolveTranslationFlow:

    @pytest.mark.asyncio
    async def test_keep_confirms_status_without_changing_english(self):
        from src.db.services.card_service import update_card

        card = SimpleNamespace(
            id=1, thai="รถไฟ", english="bicycle",
            translation_status="flagged", translation_candidates='["train"]',
        )
        mock_db = AsyncMock()

        with patch("src.db.services.embedding_service.embed_card", new=AsyncMock()) as mock_embed:
            result = await update_card(
                mock_db, card, translation_status="confirmed", translation_candidates=None
            )

        assert result.translation_status == "confirmed"
        assert result.translation_candidates is None
        assert result.english == "bicycle"  # material value untouched
        mock_embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_correct_updates_english_and_reembeds(self):
        from src.db.services.card_service import update_card

        card = SimpleNamespace(
            id=1, thai="รถไฟ", english="bicycle",
            translation_status="flagged", translation_candidates='["train"]',
        )
        mock_db = AsyncMock()

        with patch("src.db.services.embedding_service.embed_card", new=AsyncMock()) as mock_embed:
            result = await update_card(
                mock_db, card,
                english="train", translation_status="confirmed", translation_candidates=None,
            )

        assert result.english == "train"
        assert result.translation_status == "confirmed"
        assert result.translation_candidates is None
        mock_embed.assert_awaited_once_with(mock_db, card.id)
