"""
Tests for src/utils/confusables.py — deterministic phonetic/orthographic/tone
confusable-pair detection.

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_confusables.py -v
"""
import pytest

from src.config.settings import Settings
from src.utils.confusables import (
    generate_candidate_pairs,
    is_confusable,
    orthographic_distance,
    phonetic_distance,
)

DEFAULT_SETTINGS = Settings()


class TestOrthographicDistance:

    def test_identical_strings_zero(self):
        assert orthographic_distance("เสือ", "เสือ") == 0

    def test_single_char_insertion_is_one(self):
        assert orthographic_distance("เสือ", "เสื้อ") == 1

    def test_completely_different_strings(self):
        assert orthographic_distance("แมว", "หนังสือ") > 3

    def test_empty_strings(self):
        assert orthographic_distance("", "") == 0
        assert orthographic_distance("ก", "") == 1


class TestPhoneticDistance:

    def test_identical_ipa_zero(self):
        assert phonetic_distance("sɯa", "sɯa") == 0.0

    def test_one_phone_substitution_normalized(self):
        # "sɯa" vs "sɯe" — 1 edit / 3 chars
        assert phonetic_distance("sɯa", "sɯe") == pytest.approx(1 / 3)

    def test_tolerant_of_length_difference(self):
        # Normalizes by the longer string, not the shorter.
        d = phonetic_distance("ma", "maːw")
        assert d == pytest.approx(2 / 4)

    def test_empty_ipa_is_zero_distance(self):
        assert phonetic_distance("", "") == 0.0


class TestIsConfusable:

    def test_known_tone_minimal_pair(self):
        """เสือ (tiger) / เสื้อ (shirt) — same segmental skeleton, different tone."""
        a = {"thai": "เสือ", "romanization_ipa": "sɯa", "tone_pattern": ["rising"]}
        b = {"thai": "เสื้อ", "romanization_ipa": "sɯa", "tone_pattern": ["falling"]}
        reason = is_confusable(a, b, DEFAULT_SETTINGS)
        assert reason is not None
        assert "tone" in reason

    def test_look_alike_pair_one_char_difference(self):
        """No IPA available — pure orthographic signal, one character apart."""
        a = {"thai": "กา", "romanization_ipa": None, "tone_pattern": None}
        b = {"thai": "ขา", "romanization_ipa": None, "tone_pattern": None}
        assert is_confusable(a, b, DEFAULT_SETTINGS) == "orthographic"

    def test_unrelated_dissimilar_pair_is_none(self):
        a = {"thai": "แมว", "romanization_ipa": "mɛːw", "tone_pattern": ["mid"]}
        b = {"thai": "หนังสือ", "romanization_ipa": "naŋsɯː", "tone_pattern": ["mid", "rising"]}
        assert is_confusable(a, b, DEFAULT_SETTINGS) is None

    def test_identical_word_is_not_confusable_with_itself(self):
        a = {"thai": "เสือ", "romanization_ipa": "sɯa", "tone_pattern": ["rising"]}
        b = {"thai": "เสือ", "romanization_ipa": "sɯa", "tone_pattern": ["rising"]}
        assert is_confusable(a, b, DEFAULT_SETTINGS) is None

    def test_words_below_min_length_are_skipped(self):
        a = {"thai": "ก", "romanization_ipa": "k", "tone_pattern": ["mid"]}
        b = {"thai": "ข", "romanization_ipa": "kʰ", "tone_pattern": ["low"]}
        assert is_confusable(a, b, DEFAULT_SETTINGS) is None

    def test_phonetic_signal_without_orthographic_overlap(self):
        settings = Settings(confusable_max_phonetic=0.5, confusable_max_orthographic=0)
        a = {"thai": "กา", "romanization_ipa": "kaː", "tone_pattern": ["mid"]}
        b = {"thai": "ขา", "romanization_ipa": "kʰaː", "tone_pattern": ["rising"]}
        reason = is_confusable(a, b, settings)
        assert reason is not None
        assert "phonetic" in reason


class TestGenerateCandidatePairs:

    def test_shared_bigram_pair_is_blocked_in(self):
        cards = [
            {"thai": "เสือ", "romanization_ipa": "sɯa"},
            {"thai": "เสื้อ", "romanization_ipa": "sɯa"},
        ]
        pairs = generate_candidate_pairs(cards)
        assert (0, 1) in pairs

    def test_no_shared_bigram_and_far_length_is_not_blocked_in(self):
        cards = [
            {"thai": "แมว", "romanization_ipa": "mɛːw"},
            {"thai": "หนังสือพิมพ์", "romanization_ipa": "naŋsɯːpʰim"},
        ]
        pairs = generate_candidate_pairs(cards)
        assert (0, 1) not in pairs
        assert pairs == set()
