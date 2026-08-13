"""
Tests for src/utils/thai_repetition.py — the ๆ (mai yamok) expansion that fixes
romanization not repeating reduplicated words (e.g. เรื่อยๆ -> "rueai" instead
of "rueai rueai").

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_thai_repetition.py -v
"""
import pytest

from src.utils.thai_repetition import expand_repetition_marks
from src.utils.rtgs import thai_to_rtgs


class TestExpandRepetitionMarks:
    def test_mark_attached_to_word(self):
        assert expand_repetition_marks("เรื่อยๆ") == "เรื่อย เรื่อย"

    def test_mark_as_separate_token(self):
        assert expand_repetition_marks("เด็ก ๆ") == "เด็ก เด็ก"

    def test_multiple_marks_in_one_string(self):
        assert expand_repetition_marks("มากๆ ช้าๆ") == "มาก มาก ช้า ช้า"

    def test_no_mark_is_unchanged(self):
        assert expand_repetition_marks("เรื่อย") == "เรื่อย"

    def test_non_thai_text_is_unchanged(self):
        assert expand_repetition_marks("hello") == "hello"

    def test_empty_string(self):
        assert expand_repetition_marks("") == ""

    def test_leading_mark_with_nothing_to_repeat_is_dropped(self):
        assert expand_repetition_marks("ๆ") == ""


class TestThaiToRtgsRepetition:
    """End-to-end: the exact bug report — เรื่อยๆ romanizes to 'rueai' once
    instead of twice."""

    def test_reuai_repeats(self):
        assert thai_to_rtgs("เรื่อยๆ") == "rueai rueai"

    def test_single_word_unaffected(self):
        assert thai_to_rtgs("เรื่อย") == "rueai"

    def test_other_reduplicated_words(self):
        assert thai_to_rtgs("เด็กๆ") == "dek dek"
        assert thai_to_rtgs("มากๆ") == "mak mak"
