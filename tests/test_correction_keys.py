"""
Tests for src/utils/correction_keys.py — pure normalisation helpers behind
the correction-event log. No DB, no network.

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_correction_keys.py -v
"""
import pytest

from src.utils.correction_keys import english_norm, from_norm, thai_key


class TestThaiKey:
    def test_zero_width_variants_give_the_same_key(self):
        base = "ไม่เป็นไร"
        with_zwsp = "ไม่​เป็น‌ไร‍"
        assert thai_key(base) == thai_key(with_zwsp)

    def test_whitespace_variants_give_the_same_key(self):
        assert thai_key("ไม่ เป็นไร") == thai_key("ไม่   เป็นไร")
        assert thai_key(" ไม่เป็นไร ") == thai_key("ไม่เป็นไร")

    def test_replacement_character_raises(self):
        with pytest.raises(ValueError):
            thai_key("ไม่�เป็นไร")


class TestEnglishNorm:
    def test_quote_and_trailing_period_are_equal_to_bare_form(self):
        assert english_norm("You're welcome.") == english_norm("you're welcome")

    def test_surrounding_quotes_stripped(self):
        assert english_norm('"never mind"') == english_norm("never mind")

    def test_trailing_punctuation_variants_are_equal(self):
        assert english_norm("Really?") == english_norm("really")
        assert english_norm("Wow!") == english_norm("wow")

    def test_the_bill_and_bill_are_different(self):
        assert english_norm("the bill") != english_norm("bill")

    def test_whitespace_collapsed(self):
        assert english_norm("never   mind") == english_norm("never mind")


class TestFromNorm:
    def test_translation_uses_english_norm(self):
        assert from_norm("translation", {"english": "You're welcome."}) == english_norm("you're welcome")

    def test_translation_missing_english_returns_none(self):
        assert from_norm("translation", {}) is None

    def test_compound_joins_part_gloss_pairs(self):
        parts = [
            {"thai": "น้ำ", "gloss": "Water."},
            {"thai": "แข็ง", "gloss": None},
        ]
        assert from_norm("compound", {"parts": parts}) == "น้ำ=water|แข็ง="

    def test_other_targets_return_none(self):
        assert from_norm("romanization", {"romanization": "x"}) is None
        assert from_norm("other", {"anything": 1}) is None

    def test_none_from_value_returns_none(self):
        assert from_norm("translation", None) is None
