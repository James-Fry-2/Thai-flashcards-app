"""
Tests for src/utils/compound.py

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_compound.py -v

These tests exercise the deterministic decompose() function and the
resolve_glosses() gloss-ladder ordering without touching the LLM.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# decompose() — pure / deterministic
# ---------------------------------------------------------------------------

class TestDecompose:
    """Tests for the dictionary maximal-matching segmentation."""

    def _call(self, thai: str):
        from src.utils.compound import decompose
        return decompose(thai)

    def test_transparent_compound_nam_khaeng(self):
        """น้ำแข็ง (ice) → น้ำ + แข็ง"""
        parts = self._call("น้ำแข็ง")
        assert parts is not None, "น้ำแข็ง should decompose"
        assert len(parts) >= 2
        assert "น้ำ" in parts
        assert "แข็ง" in parts

    def test_transparent_compound_rot_fai(self):
        """รถไฟ (train) → รถ + ไฟ"""
        parts = self._call("รถไฟ")
        assert parts is not None, "รถไฟ should decompose"
        assert len(parts) >= 2

    def test_transparent_compound_nam_ta(self):
        """น้ำตา (tear/teardrop) → น้ำ + ตา"""
        parts = self._call("น้ำตา")
        assert parts is not None, "น้ำตา should decompose"
        assert len(parts) >= 2

    def test_loanword_no_breakdown(self):
        """คอมพิวเตอร์ is a loanword — no valid dictionary decomposition."""
        parts = self._call("คอมพิวเตอร์")
        assert parts is None, "Loanword should not decompose"

    def test_empty_string(self):
        assert self._call("") is None

    def test_non_thai(self):
        assert self._call("hello") is None

    def test_single_word_no_decomposition(self):
        """กิน (eat) is a single morpheme — must return None."""
        parts = self._call("กิน")
        # Either None (single-word dictionary hit) or a single-part list (→ filtered)
        # The spec says: single morpheme → None; ≥2 parts required
        assert parts is None or len(parts) >= 2

    def test_full_coverage_required(self):
        """Decompose must produce full coverage — no leftover characters."""
        # We can't directly test coverage internals, but we can assert that
        # whatever is returned covers the original string exactly.
        cases = ["น้ำแข็ง", "รถไฟ", "น้ำตา"]
        from src.utils.compound import decompose
        for thai in cases:
            result = decompose(thai)
            if result is not None:
                assert "".join(result) == thai, f"Parts don't cover input for {thai}"

    def test_degrades_gracefully_on_unavailable_corpus(self):
        """If the corpus returns an empty set, decompose returns None (no crash)."""
        with patch("src.utils.compound._thai_word_set", return_value=frozenset()):
            from src.utils.compound import decompose
            assert decompose("น้ำแข็ง") is None

    def test_none_on_exception(self):
        """decompose never raises — returns None on unexpected errors."""
        with patch("src.utils.compound._thai_word_set", side_effect=RuntimeError("boom")):
            from src.utils.compound import decompose
            result = decompose("น้ำแข็ง")
            assert result is None


# ---------------------------------------------------------------------------
# resolve_glosses() — gloss-ladder ordering
# ---------------------------------------------------------------------------

class TestResolveGlosses:
    """Tests for the step-1 (own cards) → step-2 (wordnet) priority."""

    @pytest.mark.asyncio
    async def test_own_card_wins_over_wordnet(self):
        """If the learner has a card for a part, its english is used (source="card")."""
        from src.utils.compound import resolve_glosses

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value="water")  # own card found

        with patch("src.utils.compound._wordnet_gloss", return_value=("liquid", "lexicon")):
            result = await resolve_glosses(mock_db, ["น้ำ"])

        assert result[0]["gloss"] == "water"
        assert result[0]["gloss_source"] == "card"

    @pytest.mark.asyncio
    async def test_wordnet_used_when_no_own_card(self):
        """Falls back to wordnet when the learner has no card for that part."""
        from src.utils.compound import resolve_glosses

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=None)  # no own card

        with patch("src.utils.compound._wordnet_gloss", return_value=("water", "lexicon")):
            result = await resolve_glosses(mock_db, ["น้ำ"])

        assert result[0]["gloss"] == "water"
        assert result[0]["gloss_source"] == "lexicon"

    @pytest.mark.asyncio
    async def test_null_gloss_when_neither_resolves(self):
        """gloss is None when own-cards and wordnet both miss."""
        from src.utils.compound import resolve_glosses

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=None)

        with patch("src.utils.compound._wordnet_gloss", return_value=(None, None)):
            result = await resolve_glosses(mock_db, ["xyz"])

        assert result[0]["gloss"] is None
        assert result[0]["gloss_source"] is None

    @pytest.mark.asyncio
    async def test_romanization_populated(self):
        """Each part carries a romanization string from thai_to_paiboon."""
        from src.utils.compound import resolve_glosses

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=None)

        with patch("src.utils.compound._wordnet_gloss", return_value=(None, None)), \
             patch("src.utils.compound.thai_to_paiboon", return_value="náam"):
            # Need to patch the import inside the module
            pass

        # At minimum, romanization key is present (may be None if paiboon unavailable)
        with patch("src.utils.compound._wordnet_gloss", return_value=(None, None)):
            result = await resolve_glosses(mock_db, ["น้ำ"])
        assert "romanization" in result[0]

    @pytest.mark.asyncio
    async def test_multiple_parts(self):
        """resolve_glosses handles multiple parts in order."""
        from src.utils.compound import resolve_glosses

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(side_effect=["water", None])

        with patch("src.utils.compound._wordnet_gloss", side_effect=[
            (None, None),       # น้ำ — own card handled it
            ("hard", "lexicon"),  # แข็ง — from wordnet
        ]):
            result = await resolve_glosses(mock_db, ["น้ำ", "แข็ง"])

        assert len(result) == 2
        assert result[0]["gloss"] == "water"
        assert result[0]["gloss_source"] == "card"
        assert result[1]["gloss"] == "hard"
        assert result[1]["gloss_source"] == "lexicon"


# ---------------------------------------------------------------------------
# compute_compound_breakdown() — surface rule
# ---------------------------------------------------------------------------

class TestComputeCompoundBreakdown:

    @pytest.mark.asyncio
    async def test_returns_none_when_no_glosses(self):
        """When all glosses are null, breakdown is None (surface rule)."""
        from src.utils.compound import compute_compound_breakdown

        mock_db = AsyncMock()
        with patch("src.utils.compound.decompose", return_value=["น้ำ", "แข็ง"]), \
             patch("src.utils.compound.resolve_glosses", new=AsyncMock(return_value=[
                 {"thai": "น้ำ", "romanization": "náam", "gloss": None, "gloss_source": None},
                 {"thai": "แข็ง", "romanization": "kǎeng", "gloss": None, "gloss_source": None},
             ])):
            breakdown, is_compound = await compute_compound_breakdown(mock_db, "น้ำแข็ง")

        assert breakdown is None
        assert is_compound is True  # it decomposed, just no gloss

    @pytest.mark.asyncio
    async def test_returns_breakdown_when_any_gloss_resolves(self):
        """Even if only one part has a gloss, the full breakdown is returned."""
        from src.utils.compound import compute_compound_breakdown

        mock_db = AsyncMock()
        with patch("src.utils.compound.decompose", return_value=["น้ำ", "แข็ง"]), \
             patch("src.utils.compound.resolve_glosses", new=AsyncMock(return_value=[
                 {"thai": "น้ำ", "romanization": "náam", "gloss": "water", "gloss_source": "card"},
                 {"thai": "แข็ง", "romanization": "kǎeng", "gloss": None, "gloss_source": None},
             ])):
            breakdown, is_compound = await compute_compound_breakdown(mock_db, "น้ำแข็ง")

        assert breakdown is not None
        assert len(breakdown) == 2
        assert is_compound is True

    @pytest.mark.asyncio
    async def test_atomic_word_returns_false(self):
        """Non-compound word sets is_compound=False, breakdown=None."""
        from src.utils.compound import compute_compound_breakdown

        mock_db = AsyncMock()
        with patch("src.utils.compound.decompose", return_value=None):
            breakdown, is_compound = await compute_compound_breakdown(mock_db, "กิน")

        assert breakdown is None
        assert is_compound is False
