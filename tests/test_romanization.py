"""
Tests for the ห นำ tokenisation fix and the tltk-based RTGS rewrite (#1).

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_romanization.py -v
"""
import unicodedata

from src.utils.thai_tokenize import merge_orphan_hor_nam
from src.utils.paiboon import thai_to_paiboon
from src.utils.rtgs import thai_to_rtgs
from src.utils.ipa_romanization import thai_to_ipa


def _paiboon(text: str) -> str:
    """NFC-normalise: Paiboon+ tones are combining diacritics, and Python
    source literals for accented letters are precomposed."""
    return unicodedata.normalize("NFC", thai_to_paiboon(text))


class TestMergeOrphanHorNam:
    def test_orphan_hor_token_merges_into_sonorant(self):
        assert merge_orphan_hor_nam(["กะ", "ห", "ลำ", "ปลี"]) == ["กะ", "หลำ", "ปลี"]

    def test_trailing_hor_on_token_moves_across(self):
        assert merge_orphan_hor_nam(["กะห", "ลำ"]) == ["กะ", "หลำ"]

    def test_hor_before_non_sonorant_untouched(self):
        assert merge_orphan_hor_nam(["ห", "า"]) == ["ห", "า"]

    def test_trailing_lone_hor_is_kept(self):
        assert merge_orphan_hor_nam(["กิน", "ห"]) == ["กิน", "ห"]


class TestPaiboon:
    def test_orphan_hor_nam_word(self):
        assert _paiboon("กะหลำปลี") == "gà lǎm bplii"

    def test_hor_nam_words_unaffected(self):
        assert _paiboon("หมู") == "mǔu"
        assert _paiboon("หน้า") == "nâa"
        assert _paiboon("หาย") == "hǎai"

    def test_correctly_spelled_word_still_hyphenated(self):
        assert _paiboon("กะหล่ำปลี") == "gà-làm-bplii"


class TestIpa:
    def test_orphan_hor_nam_word(self):
        assert thai_to_ipa("กะหลำปลี") == "ka lam pliː"

    def test_no_stray_hor_syllable(self):
        for word in ("กะหลำปลี", "หมู", "หน้า", "หาย", "ไหน"):
            assert "hɔː" not in thai_to_ipa(word)


class TestRtgs:
    def test_orphan_hor_nam_word(self):
        assert thai_to_rtgs("กะหลำปลี") == "ka lam pli"

    def test_hor_nam_words(self):
        assert thai_to_rtgs("หมู") == "mu"
        assert thai_to_rtgs("หน้า") == "na"
        assert thai_to_rtgs("หาย") == "hai"
        assert thai_to_rtgs("ใหม่") == "mai"

    def test_royin_regressions_fixed(self):
        assert thai_to_rtgs("สวัสดี") == "sawatdi"
        assert thai_to_rtgs("สหรัฐ") == "saharat"
        assert thai_to_rtgs("ข้าวเหนียว") == "khaoniao"
        assert thai_to_rtgs("ครับ") == "khrap"
        assert thai_to_rtgs("เชียงใหม่") == "chiangmai"


class TestNonThaiPassthrough:
    def test_ascii_unchanged(self):
        assert thai_to_paiboon("ABC 123") == "ABC 123"
        assert thai_to_rtgs("ABC 123") == "ABC 123"
        assert thai_to_ipa("ABC 123") == "ABC 123"

    def test_empty_string(self):
        assert thai_to_paiboon("") == ""
        assert thai_to_rtgs("") == ""
        assert thai_to_ipa("") == ""
