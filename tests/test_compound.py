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
# pick_best_gloss() — sense selection among an ordered translation list
# ---------------------------------------------------------------------------

class TestPickBestGloss:

    def test_picks_common_sense_over_technical_ones(self):
        """The real รัก ordering: binomial + common-name + rare-word entries
        precede the everyday senses. Frequency ranking should surface one of
        those, not the scientific/technical ones."""
        from src.utils.compound import pick_best_gloss

        result = pick_best_gloss(
            ["Calotropis gigantea", "Crown flower", "lacquer", "love", "like"]
        )
        assert result in ("love", "like")

    def test_binomial_only_list_returns_none(self):
        from src.utils.compound import pick_best_gloss

        assert pick_best_gloss(["Calotropis gigantea"]) is None

    def test_binomial_dropped_leaves_first_non_binomial(self):
        """When frequency data can't separate the remaining candidates
        further, a binomial is still excluded from consideration."""
        from src.utils.compound import pick_best_gloss

        result = pick_best_gloss(["Calotropis gigantea", "lacquer"])
        assert result == "lacquer"

    def test_empty_list_returns_none(self):
        from src.utils.compound import pick_best_gloss

        assert pick_best_gloss([]) is None

    def test_ordinary_capitalized_phrase_not_treated_as_binomial(self):
        """'Crown flower' has the same capitalized+lowercase shape as a
        binomial but both words are real English — it must survive the
        binomial filter (even though frequency ranking still demotes it
        below 'love')."""
        from src.utils.compound import pick_best_gloss

        result = pick_best_gloss(["Crown flower", "xyzzyqq"])
        assert result == "Crown flower"

    def test_bare_pronoun_excluded_even_though_it_is_the_most_frequent_word(self):
        """Regression: พี่/น้อง double as first/second-person pronouns in
        Volubilis, and "I"/"you" are near-unbeatable on raw English word
        frequency — pick_best_gloss must not let that outrank the word's
        dominant noun sense."""
        from src.utils.compound import pick_best_gloss

        result = pick_best_gloss(["I", "you", "younger brother", "younger sister"])
        assert result in ("younger brother", "younger sister")

    def test_pronoun_only_list_returns_none(self):
        from src.utils.compound import pick_best_gloss

        assert pick_best_gloss(["I", "you"]) is None

    def test_qualified_pronoun_variant_is_not_excluded(self):
        """Only an exact bare pronoun is dropped — a qualified variant like
        this one is a different string and survives the filter."""
        from src.utils.compound import pick_best_gloss

        result = pick_best_gloss(["you (to s.o. older, inf.)"])
        assert result == "you (to s.o. older, inf.)"

    def test_number_word_one_is_not_treated_as_a_pronoun(self):
        """"one" is a real, correct gloss for numeral compounds (หนึ่งทุ่ม =
        "one" + "o'clock") and must not be swept up by the pronoun filter."""
        from src.utils.compound import pick_best_gloss

        result = pick_best_gloss(["one"])
        assert result == "one"


# ---------------------------------------------------------------------------
# select_gloss_by_level() — Level-ranked sense selection
# ---------------------------------------------------------------------------

class TestSelectGlossByLevel:

    def test_ranks_by_level_over_source_order(self):
        """A later, lower-level ("B") sense beats an earlier NULL/higher-level
        sense — this is the whole point of switching off frequency-only
        ranking."""
        from src.utils.compound import select_gloss_by_level

        senses = [
            {"english": "Crown flower", "level": None, "pos": "n."},
            {"english": "lacquer", "level": None, "pos": "n."},
            {"english": "love", "level": "B", "pos": "v."},
            {"english": "like", "level": "B", "pos": "v."},
        ]
        result = select_gloss_by_level(senses)
        assert result in ("love", "like")

    def test_drops_scientific_binomial_even_at_best_level(self):
        """A binomial-shaped sense must never win, regardless of its level —
        science is excluded before ranking, not after."""
        from src.utils.compound import select_gloss_by_level

        senses = [
            {"english": "Calotropis gigantea", "level": "B", "pos": "n."},
            {"english": "lacquer", "level": "A2", "pos": "n."},
        ]
        result = select_gloss_by_level(senses)
        assert result == "lacquer"

    def test_ties_within_a_level_broken_by_frequency(self):
        """Two senses at the same best level fall back to pick_best_gloss's
        frequency ranking rather than raw source order."""
        from src.utils.compound import select_gloss_by_level

        senses = [
            {"english": "cherish", "level": "B", "pos": "v."},
            {"english": "love", "level": "B", "pos": "v."},
        ]
        result = select_gloss_by_level(senses)
        assert result == "love"

    def test_all_null_levels_falls_back_to_frequency_ranking(self):
        """When the source file carries no level data at all for this entry,
        behaviour must be identical to plain pick_best_gloss — the pre-Level
        default."""
        from src.utils.compound import select_gloss_by_level, pick_best_gloss

        senses = [
            {"english": "Calotropis gigantea", "level": None, "pos": "n."},
            {"english": "Crown flower", "level": None, "pos": "n."},
            {"english": "lacquer", "level": None, "pos": "n."},
            {"english": "love", "level": None, "pos": "v."},
            {"english": "like", "level": None, "pos": "v."},
        ]
        expected = pick_best_gloss([s["english"] for s in senses])
        assert select_gloss_by_level(senses) == expected

    def test_empty_list_returns_none(self):
        from src.utils.compound import select_gloss_by_level

        assert select_gloss_by_level([]) is None

    def test_all_binomial_returns_none(self):
        from src.utils.compound import select_gloss_by_level

        senses = [{"english": "Calotropis gigantea", "level": "B", "pos": "n."}]
        assert select_gloss_by_level(senses) is None


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

        # At minimum, romanization key is present (may be None if paiboon unavailable)
        with patch("src.utils.compound._wordnet_gloss", return_value=(None, None)):
            result = await resolve_glosses(mock_db, ["น้ำ"])
        assert "romanization" in result[0]

    @pytest.mark.asyncio
    async def test_volubilis_step_resolves_common_sense_not_scientific_name(self):
        """Regression for the real รัก entry with no level data (this is
        what the file actually carries today): lookup_ranked returns senses
        headed by a scientific binomial and a plant common name before the
        everyday senses, all with level=None. The Volubilis step must not
        blindly take the first one — it degrades to pick_best_gloss's
        frequency ranking and surfaces "love"/"like"."""
        from src.utils.compound import resolve_glosses

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=None)  # no own card

        rak_senses = [
            {"english": e, "level": None, "pos": None} for e in (
                "Calotropis gigantea", "Crown flower", "lacquer", "love",
                "be fond of", "be keen on", "cherish", "adore", "like",
            )
        ]
        with patch("src.db.services.lexicon_service.lookup_ranked", new=AsyncMock(return_value=rak_senses)):
            result = await resolve_glosses(mock_db, ["รัก"])

        assert result[0]["gloss"] in ("love", "like")
        assert result[0]["gloss_source"] == "volubilis"

    @pytest.mark.asyncio
    async def test_volubilis_step_uses_level_when_present(self):
        """When the lexicon does carry level data, a "B"-level sense wins
        over an earlier NULL-level sense, even though frequency ranking
        alone might have picked differently."""
        from src.utils.compound import resolve_glosses

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=None)  # no own card

        senses = [
            {"english": "Crown flower", "level": None, "pos": "n."},
            {"english": "lacquer", "level": None, "pos": "n."},
            {"english": "love", "level": "B", "pos": "v."},
        ]
        with patch("src.db.services.lexicon_service.lookup_ranked", new=AsyncMock(return_value=senses)):
            result = await resolve_glosses(mock_db, ["รัก"])

        assert result[0]["gloss"] == "love"
        assert result[0]["gloss_source"] == "volubilis"

    @pytest.mark.asyncio
    async def test_multiple_parts(self):
        """resolve_glosses handles multiple parts in order."""
        from src.utils.compound import resolve_glosses

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(side_effect=["water", None])

        # _wordnet_gloss is only called for แข็ง — น้ำ short-circuits on the
        # own-card hit and never reaches the wordnet step.
        with patch("src.utils.compound._wordnet_gloss", return_value=("hard", "lexicon")):
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
        """When all glosses are null, breakdown is None (surface guard)."""
        from src.utils.compound import compute_compound_breakdown

        mock_db = AsyncMock()
        with patch("src.utils.compound.decompose", return_value=["น้ำ", "แข็ง"]), \
             patch("src.utils.compound.resolve_glosses", new=AsyncMock(return_value=[
                 {"thai": "น้ำ", "romanization": "náam", "gloss": None, "gloss_source": None},
                 {"thai": "แข็ง", "romanization": "kǎeng", "gloss": None, "gloss_source": None},
             ])):
            breakdown, is_compound = await compute_compound_breakdown(mock_db, "น้ำแข็ง")

        assert breakdown is None
        assert is_compound is True  # it decomposed, just not surfaced

    @pytest.mark.asyncio
    async def test_guard_suppresses_when_one_part_glossless(self):
        """โทน + สำ + เสียง: สำ never glosses, so under the default (ratio=1.0)
        guard the breakdown is suppressed even though 2 of 3 parts glossed.
        is_compound stays True — it's a structural fact, independent of the guard."""
        from src.utils.compound import compute_compound_breakdown

        mock_db = AsyncMock()
        with patch("src.utils.compound.decompose", return_value=["โทน", "สำ", "เสียง"]), \
             patch("src.utils.compound.resolve_glosses", new=AsyncMock(return_value=[
                 {"thai": "โทน", "romanization": "ton", "gloss": "tone", "gloss_source": "card"},
                 {"thai": "สำ", "romanization": "sam", "gloss": None, "gloss_source": None},
                 {"thai": "เสียง", "romanization": "siang", "gloss": "sound", "gloss_source": "lexicon"},
             ])):
            breakdown, is_compound = await compute_compound_breakdown(mock_db, "โทนสำเสียง")

        assert breakdown is None
        assert is_compound is True

    @pytest.mark.asyncio
    async def test_guard_passes_when_all_parts_gloss(self):
        """When every part resolves a gloss, the breakdown surfaces."""
        from src.utils.compound import compute_compound_breakdown

        mock_db = AsyncMock()
        with patch("src.utils.compound.decompose", return_value=["น้ำ", "แข็ง"]), \
             patch("src.utils.compound.resolve_glosses", new=AsyncMock(return_value=[
                 {"thai": "น้ำ", "romanization": "náam", "gloss": "water", "gloss_source": "card"},
                 {"thai": "แข็ง", "romanization": "kǎeng", "gloss": "hard", "gloss_source": "lexicon"},
             ])):
            breakdown, is_compound = await compute_compound_breakdown(mock_db, "น้ำแข็ง")

        assert breakdown is not None
        assert len(breakdown) == 2
        assert is_compound is True

    @pytest.mark.asyncio
    async def test_morpheme_map_lets_kwaam_suk_surface(self):
        """ความสุข → ความ (morpheme map) + สุข (own card/lexicon) — both glossed,
        so it surfaces with ความ's gloss_source="morpheme"."""
        from src.utils.compound import compute_compound_breakdown

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=None)  # no own cards
        with patch("src.utils.compound.decompose", return_value=["ความ", "สุข"]), \
             patch("src.utils.compound._wordnet_gloss", return_value=("happy", "lexicon")), \
             patch("src.db.services.lexicon_service.lookup_ranked", new=AsyncMock(return_value=[])):
            breakdown, is_compound = await compute_compound_breakdown(mock_db, "ความสุข")

        assert is_compound is True
        assert breakdown is not None
        assert breakdown[0]["thai"] == "ความ"
        assert breakdown[0]["gloss_source"] == "morpheme"
        assert breakdown[1]["gloss"] == "happy"

    @pytest.mark.asyncio
    async def test_surface_ratio_override_allows_partial_gloss(self):
        """Lowering compound_surface_min_gloss_ratio to 0.5 lets a 1-of-2-glossed
        breakdown surface, where the default (1.0) would suppress it."""
        from src.utils.compound import compute_compound_breakdown
        from src.config.settings import Settings

        mock_db = AsyncMock()
        lenient_settings = Settings(compound_surface_min_gloss_ratio=0.5)
        with patch("src.utils.compound.decompose", return_value=["น้ำ", "แข็ง"]), \
             patch("src.utils.compound.resolve_glosses", new=AsyncMock(return_value=[
                 {"thai": "น้ำ", "romanization": "náam", "gloss": "water", "gloss_source": "card"},
                 {"thai": "แข็ง", "romanization": "kǎeng", "gloss": None, "gloss_source": None},
             ])), \
             patch("src.config.settings.get_settings", return_value=lenient_settings):
            breakdown, is_compound = await compute_compound_breakdown(mock_db, "น้ำแข็ง")

        assert breakdown is not None
        assert is_compound is True

    @pytest.mark.asyncio
    async def test_naa_rak_breakdown_glosses_rak_as_love_not_plant_sense(self):
        """End-to-end regression for the original bug report: น่ารัก →
        น่า (morpheme map) + รัก (Volubilis, real sense ordering incl. the
        binomial) must surface รัก as "love"/"like", not a scientific or
        technical sense."""
        from src.utils.compound import compute_compound_breakdown

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=None)  # no own cards

        rak_senses = [
            {"english": e, "level": None, "pos": None} for e in (
                "Calotropis gigantea", "Crown flower", "lacquer", "love",
                "be fond of", "be keen on", "cherish", "adore", "like",
            )
        ]
        with patch("src.utils.compound.decompose", return_value=["น่า", "รัก"]), \
             patch("src.db.services.lexicon_service.lookup_ranked", new=AsyncMock(return_value=rak_senses)):
            breakdown, is_compound = await compute_compound_breakdown(mock_db, "น่ารัก")

        assert is_compound is True
        assert breakdown is not None
        rak_part = next(p for p in breakdown if p["thai"] == "รัก")
        assert rak_part["gloss"] in ("love", "like")
        assert rak_part["gloss_source"] == "volubilis"

    @pytest.mark.asyncio
    async def test_nong_saao_breakdown_glosses_nong_as_sibling_not_pronoun(self):
        """End-to-end regression for the น้องสาว bug report: น้อง and พี่
        double as first/second-person pronouns in Volubilis, and "I"/"you"
        used to win purely on English word frequency. น้อง must surface as a
        sibling sense, not "I" (real sense list captured from the live
        lexicon)."""
        from src.utils.compound import compute_compound_breakdown

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=None)  # no own cards

        nong_senses = [
            {"english": e, "level": None, "pos": None} for e in (
                "younger brother", "younger sister", "younger person",
                "miss", "young lady", "I", "you",
            )
        ]
        saao_senses = [
            {"english": e, "level": None, "pos": None} for e in (
                "young girl", "young lady", "maiden", "unmarried girl", "girl",
            )
        ]

        async def fake_lookup_ranked(db, thai_part):
            return nong_senses if thai_part == "น้อง" else saao_senses

        with patch("src.utils.compound.decompose", return_value=["น้อง", "สาว"]), \
             patch("src.db.services.lexicon_service.lookup_ranked", new=AsyncMock(side_effect=fake_lookup_ranked)):
            breakdown, is_compound = await compute_compound_breakdown(mock_db, "น้องสาว")

        assert is_compound is True
        assert breakdown is not None
        nong_part = next(p for p in breakdown if p["thai"] == "น้อง")
        assert nong_part["gloss"] in ("younger brother", "younger sister", "younger person")
        assert nong_part["gloss"] not in ("I", "you")

    @pytest.mark.asyncio
    async def test_atomic_word_returns_false(self):
        """Non-compound word sets is_compound=False, breakdown=None."""
        from src.utils.compound import compute_compound_breakdown

        mock_db = AsyncMock()
        with patch("src.utils.compound.decompose", return_value=None):
            breakdown, is_compound = await compute_compound_breakdown(mock_db, "กิน")

        assert breakdown is None
        assert is_compound is False


# ---------------------------------------------------------------------------
# On-demand LLM gloss fallback — src/llm/prompts/compound_breakdown.py
#
# These exercise only the pure parse/merge function. No provider is
# constructed and no network call is made.
# ---------------------------------------------------------------------------

class TestParseCompoundBreakdownResponse:

    def test_fills_only_none_glosses_and_stamps_llm_source(self):
        from src.llm.prompts.compound_breakdown import parse_compound_breakdown_response

        parts = [
            {"thai": "เสื้อ", "romanization": "seua", "gloss": "shirt", "gloss_source": "lexicon"},
            {"thai": "คลุม", "romanization": "khlum", "gloss": None, "gloss_source": None},
        ]
        raw = '{"glosses": {"คลุม": "cover"}, "confidence": "high"}'

        updated, confidence = parse_compound_breakdown_response(raw, parts)

        assert confidence == "high"
        shirt = next(p for p in updated if p["thai"] == "เสื้อ")
        khlum = next(p for p in updated if p["thai"] == "คลุม")
        assert shirt["gloss"] == "shirt"
        assert shirt["gloss_source"] == "lexicon"  # untouched — already had a gloss
        assert khlum["gloss"] == "cover"
        assert khlum["gloss_source"] == "llm"

        # Caller's original list is not mutated
        assert parts[1]["gloss"] is None

    def test_malformed_json_returns_parts_unchanged_with_none_confidence(self):
        from src.llm.prompts.compound_breakdown import parse_compound_breakdown_response

        parts = [{"thai": "ก", "romanization": None, "gloss": None, "gloss_source": None}]
        updated, confidence = parse_compound_breakdown_response("not json at all {{{", parts)

        assert confidence is None
        assert updated == parts

    def test_markdown_fenced_json_is_parsed(self):
        from src.llm.prompts.compound_breakdown import parse_compound_breakdown_response

        parts = [{"thai": "ก", "romanization": None, "gloss": None, "gloss_source": None}]
        raw = '```json\n{"glosses": {"ก": "thing"}, "confidence": "medium"}\n```'
        updated, confidence = parse_compound_breakdown_response(raw, parts)

        assert confidence == "medium"
        assert updated[0]["gloss"] == "thing"
        assert updated[0]["gloss_source"] == "llm"

    def test_non_json_text_returns_parts_unchanged(self):
        from src.llm.prompts.compound_breakdown import parse_compound_breakdown_response

        parts = [{"thai": "ก", "romanization": None, "gloss": None, "gloss_source": None}]
        updated, confidence = parse_compound_breakdown_response(
            "Sure, here's the breakdown you asked for.", parts
        )

        assert confidence is None
        assert updated == parts

    def test_unknown_part_name_in_response_is_ignored(self):
        from src.llm.prompts.compound_breakdown import parse_compound_breakdown_response

        parts = [{"thai": "ก", "romanization": None, "gloss": None, "gloss_source": None}]
        raw = '{"glosses": {"ข": "something else"}, "confidence": "low"}'
        updated, confidence = parse_compound_breakdown_response(raw, parts)

        assert confidence == "low"
        assert updated[0]["gloss"] is None  # "ข" isn't a known part; ignored
        assert updated[0]["gloss_source"] is None

    def test_invalid_confidence_value_becomes_none(self):
        from src.llm.prompts.compound_breakdown import parse_compound_breakdown_response

        parts = [{"thai": "ก", "romanization": None, "gloss": None, "gloss_source": None}]
        raw = '{"glosses": {}, "confidence": "very high"}'
        _, confidence = parse_compound_breakdown_response(raw, parts)

        assert confidence is None


# ---------------------------------------------------------------------------
# compound_llm_service.enrich_breakdown — the cost-guard short-circuit and
# the not_compound early-exits must never construct a provider (no network
# call). The LLM call itself is mocked when it is expected to happen.
# ---------------------------------------------------------------------------

class TestEnrichBreakdownService:

    def _make_card(self, is_compound=True, compound_breakdown=None):
        card = MagicMock()
        card.is_compound = is_compound
        card.compound_breakdown = compound_breakdown
        card.thai = "เสื้อคลุม"
        card.romanization = "seua khlum"
        card.english = "overcoat"
        return card

    @pytest.mark.asyncio
    async def test_not_compound_card_returns_early_without_provider(self):
        from src.db.services import compound_llm_service
        import json as json_mod

        card = self._make_card(is_compound=False, compound_breakdown=None)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=card)

        with patch("src.db.services.compound_llm_service.get_provider") as mock_get_provider:
            result = await compound_llm_service.enrich_breakdown(mock_db, 1)

        assert result == {"status": "not_compound"}
        mock_get_provider.assert_not_called()

    @pytest.mark.asyncio
    async def test_null_breakdown_on_compound_card_falls_through_to_recompute(self):
        """A null compound_breakdown on an is_compound=True card is NOT an
        unconditional not_compound — it means the ladder found a gap and the
        surface guard held the breakdown back, so this falls through to the
        on-the-fly recompute path. See TestEnrichBreakdownService's
        'unsurfaced compound' tests for the real (mocked-ladder) exercise;
        here we only assert the provider still isn't reached before that
        recompute happens, using a card whose Thai actually decomposes."""
        from src.db.services import compound_llm_service

        card = self._make_card(is_compound=True, compound_breakdown=None)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=card)

        with patch("src.db.services.compound_llm_service.decompose", return_value=["เสื้อ", "คลุม"]), \
             patch("src.db.services.compound_llm_service.resolve_glosses", new=AsyncMock(return_value=[
                 {"thai": "เสื้อ", "romanization": "seua", "gloss": "shirt", "gloss_source": "lexicon"},
                 {"thai": "คลุม", "romanization": "khlum", "gloss": "cover", "gloss_source": "lexicon"},
             ])), \
             patch("src.db.services.compound_llm_service.get_provider") as mock_get_provider:
            result = await compound_llm_service.enrich_breakdown(mock_db, 1)

        # Both recomputed parts are already glossed -> no_gaps, no provider call
        assert result["status"] == "no_gaps"
        mock_get_provider.assert_not_called()

    @pytest.mark.asyncio
    async def test_fully_glossed_breakdown_short_circuits_without_provider(self):
        from src.db.services import compound_llm_service
        import json as json_mod

        parts = [
            {"thai": "เสื้อ", "romanization": "seua", "gloss": "shirt", "gloss_source": "lexicon"},
            {"thai": "คลุม", "romanization": "khlum", "gloss": "cover", "gloss_source": "lexicon"},
        ]
        card = self._make_card(is_compound=True, compound_breakdown=json_mod.dumps(parts, ensure_ascii=False))
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=card)

        with patch("src.db.services.compound_llm_service.get_provider") as mock_get_provider:
            result = await compound_llm_service.enrich_breakdown(mock_db, 1)

        assert result["status"] == "no_gaps"
        assert result["parts"] == parts
        mock_get_provider.assert_not_called()

    @pytest.mark.asyncio
    async def test_gap_triggers_provider_call_and_fills_gloss(self):
        from src.db.services import compound_llm_service
        from src.llm.base import LLMResponse
        import json as json_mod

        parts = [
            {"thai": "เสื้อ", "romanization": "seua", "gloss": "shirt", "gloss_source": "lexicon"},
            {"thai": "คลุม", "romanization": "khlum", "gloss": None, "gloss_source": None},
        ]
        card = self._make_card(is_compound=True, compound_breakdown=json_mod.dumps(parts, ensure_ascii=False))
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=card)

        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(return_value=LLMResponse(
            text='{"glosses": {"คลุม": "cover"}, "confidence": "high"}',
            input_tokens=250,
            output_tokens=20,
            model="claude-haiku-4-5-20251001",
        ))

        with patch("src.db.services.compound_llm_service.get_provider", return_value=mock_provider):
            result = await compound_llm_service.enrich_breakdown(mock_db, 1)

        assert result["status"] == "enriched"
        assert result["confidence"] == "high"
        assert result["filled"] == ["คลุม"]
        assert result["persisted"] is True
        # Written back to the card row (route layer commits)
        assert card.compound_breakdown != json_mod.dumps(parts, ensure_ascii=False)
        assert "cover" in card.compound_breakdown

    @pytest.mark.asyncio
    async def test_low_confidence_fill_is_not_persisted(self):
        """Regression for the เยอรมัน (German) case: decompose() can produce
        a nonsense split of a loanword transliteration, and the model can
        fabricate plausible-looking glosses for the resulting meaningless
        fragments. confidence='low' is its own signal of this — such a fill
        must be returned for display but never written to the row."""
        from src.db.services import compound_llm_service
        from src.llm.base import LLMResponse
        import json as json_mod

        parts = [
            {"thai": "เย", "romanization": None, "gloss": None, "gloss_source": None},
            {"thai": "อร", "romanization": None, "gloss": None, "gloss_source": None},
            {"thai": "มัน", "romanization": None, "gloss": "it", "gloss_source": "card"},
        ]
        card = self._make_card(is_compound=True, compound_breakdown=json_mod.dumps(parts, ensure_ascii=False))
        card.thai = "เยอรมัน"
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=card)

        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(return_value=LLMResponse(
            text='{"glosses": {"เย": "Germany", "อร": "man"}, "confidence": "low"}',
            input_tokens=291,
            output_tokens=47,
            model="claude-haiku-4-5-20251001",
        ))

        original_breakdown = card.compound_breakdown
        with patch("src.db.services.compound_llm_service.get_provider", return_value=mock_provider):
            result = await compound_llm_service.enrich_breakdown(mock_db, 1)

        assert result["status"] == "enriched"
        assert result["confidence"] == "low"
        assert result["filled"] == ["เย", "อร"]
        assert result["persisted"] is False
        # Fabricated glosses are returned for display (frontend renders them
        # as an unsaved suggestion) but the row itself is untouched.
        assert result["parts"][0]["gloss"] == "Germany"
        assert card.compound_breakdown == original_breakdown

    @pytest.mark.asyncio
    async def test_unparseable_confidence_is_not_persisted(self):
        """No confidence signal at all is treated the same as low — don't
        persist on missing/invalid confidence either."""
        from src.db.services import compound_llm_service
        from src.llm.base import LLMResponse
        import json as json_mod

        parts = [
            {"thai": "เสื้อ", "romanization": "seua", "gloss": "shirt", "gloss_source": "lexicon"},
            {"thai": "คลุม", "romanization": "khlum", "gloss": None, "gloss_source": None},
        ]
        card = self._make_card(is_compound=True, compound_breakdown=json_mod.dumps(parts, ensure_ascii=False))
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=card)

        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(return_value=LLMResponse(
            text="not valid json at all",
            input_tokens=250,
            output_tokens=5,
            model="claude-haiku-4-5-20251001",
        ))

        original_breakdown = card.compound_breakdown
        with patch("src.db.services.compound_llm_service.get_provider", return_value=mock_provider):
            result = await compound_llm_service.enrich_breakdown(mock_db, 1)

        assert result["confidence"] is None
        assert result["filled"] == []
        assert result["persisted"] is False
        assert card.compound_breakdown == original_breakdown

    @pytest.mark.asyncio
    async def test_card_not_found_returns_not_compound(self):
        from src.db.services import compound_llm_service

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        with patch("src.db.services.compound_llm_service.get_provider") as mock_get_provider:
            result = await compound_llm_service.enrich_breakdown(mock_db, 999)

        assert result == {"status": "not_compound"}
        mock_get_provider.assert_not_called()

    # -----------------------------------------------------------------
    # Not-yet-surfaced compounds — is_compound=True but compound_breakdown
    # is still null because the ladder left a gap and the default
    # compound_surface_min_gloss_ratio (1.0) held it back. The button is
    # available here too, so the service must recompute the segmentation
    # on the fly (decompose() is pure — same result as at ingestion time).
    # -----------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_unsurfaced_compound_recomputes_segmentation_and_fills_gap(self):
        from src.db.services import compound_llm_service
        from src.llm.base import LLMResponse

        card = self._make_card(is_compound=True, compound_breakdown=None)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=card)

        resolved_parts = [
            {"thai": "เสื้อ", "romanization": "seua", "gloss": "shirt", "gloss_source": "lexicon"},
            {"thai": "คลุม", "romanization": "khlum", "gloss": None, "gloss_source": None},
        ]

        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(return_value=LLMResponse(
            text='{"glosses": {"คลุม": "cover"}, "confidence": "medium"}',
            input_tokens=245,
            output_tokens=19,
            model="claude-haiku-4-5-20251001",
        ))

        with patch("src.db.services.compound_llm_service.decompose", return_value=["เสื้อ", "คลุม"]) as mock_decompose, \
             patch("src.db.services.compound_llm_service.resolve_glosses", new=AsyncMock(return_value=resolved_parts)) as mock_resolve, \
             patch("src.db.services.compound_llm_service.get_provider", return_value=mock_provider):
            result = await compound_llm_service.enrich_breakdown(mock_db, 1)

        mock_decompose.assert_called_once_with(card.thai)
        mock_resolve.assert_awaited_once_with(mock_db, ["เสื้อ", "คลุม"])
        assert result["status"] == "enriched"
        assert result["filled"] == ["คลุม"]
        assert result["persisted"] is True
        # This card had never surfaced before — the enrichment writes it for
        # the first time.
        assert card.compound_breakdown is not None
        assert "cover" in card.compound_breakdown

    @pytest.mark.asyncio
    async def test_unsurfaced_non_decomposable_word_returns_not_compound(self):
        """Defensive: if is_compound was set True by an older run but
        decompose() no longer agrees, don't call the LLM."""
        from src.db.services import compound_llm_service

        card = self._make_card(is_compound=True, compound_breakdown=None)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=card)

        with patch("src.db.services.compound_llm_service.decompose", return_value=None), \
             patch("src.db.services.compound_llm_service.get_provider") as mock_get_provider:
            result = await compound_llm_service.enrich_breakdown(mock_db, 1)

        assert result == {"status": "not_compound"}
        mock_get_provider.assert_not_called()

    @pytest.mark.asyncio
    async def test_unsurfaced_compound_with_unfillable_gap_does_not_persist(self):
        """When the LLM can't fill the missing part (e.g. a bound morpheme),
        filled is empty and compound_breakdown stays null — no false surface."""
        from src.db.services import compound_llm_service
        from src.llm.base import LLMResponse

        card = self._make_card(is_compound=True, compound_breakdown=None)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=card)

        resolved_parts = [
            {"thai": "อะ", "romanization": None, "gloss": None, "gloss_source": None},
            {"thai": "ไร", "romanization": None, "gloss": None, "gloss_source": None},
        ]

        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(return_value=LLMResponse(
            text='{"glosses": {}, "confidence": "low"}',
            input_tokens=240,
            output_tokens=10,
            model="claude-haiku-4-5-20251001",
        ))

        with patch("src.db.services.compound_llm_service.decompose", return_value=["อะ", "ไร"]), \
             patch("src.db.services.compound_llm_service.resolve_glosses", new=AsyncMock(return_value=resolved_parts)), \
             patch("src.db.services.compound_llm_service.get_provider", return_value=mock_provider):
            result = await compound_llm_service.enrich_breakdown(mock_db, 1)

        assert result["status"] == "enriched"
        assert result["filled"] == []
        assert result["persisted"] is False
        assert card.compound_breakdown is None  # never written — nothing changed
