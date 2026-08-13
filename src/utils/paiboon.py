"""
Thai script → Paiboon+ romanization.

Tokenises Thai text with PyThaiNLP (newmm), converts each token to IPA via
the tltk_ipa engine, then maps the output to Paiboon+ notation.

tltk_ipa syllable format:  [onset][vowel][ː?][coda?][1-5]
  • ʰ (U+02B0) marks aspiration on the preceding consonant
  • ː (U+02D0) marks a long vowel
  • ᴐ (U+1D10) is tltk's turned-o, equivalent to IPA ɔ
  • Tone digit 1–5: 1=mid, 2=low, 3=falling, 4=high, 5=rising
  • Syllables within a word are joined with "."

Returns an empty string on any failure so callers never crash.
"""
import re
import sys
from typing import Optional

from src.utils.thai_repetition import expand_repetition_marks

try:
    from pythainlp.transliterate import transliterate
    from pythainlp.tokenize import word_tokenize
    _PYTHAINLP_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PYTHAINLP_AVAILABLE = False

# ---------------------------------------------------------------------------
# Tone mapping:  tltk digit → Unicode combining diacritic applied to the
# first vowel letter in the Paiboon+ syllable.
# ---------------------------------------------------------------------------
_TONE: dict[str, str] = {
    "1": "",           # mid      — no mark
    "2": "\u0300",     # low      — combining grave  (à)
    "3": "\u0302",     # falling  — combining circumflex (â)
    "4": "\u0301",     # high     — combining acute  (á)
    "5": "\u030c",     # rising   — combining caron  (ǎ)
}

# ---------------------------------------------------------------------------
# Onset consonants (try longest pattern first).
# tltk_ipa uses ʰ (U+02B0) to mark aspiration.
# ---------------------------------------------------------------------------
_ONSETS: list[tuple[str, str]] = [
    # Clusters — aspirated
    ("pʰr", "pr"), ("pʰl", "pl"),
    ("kʰw", "kw"), ("kʰr", "kr"), ("kʰl", "kl"),
    # Clusters — unaspirated
    ("pr",  "bpr"), ("pl",  "bpl"),
    ("kr",  "gr"),  ("kl",  "gl"),  ("kw",  "gw"),
    ("tr",  "dtr"),
    # Aspirated simple
    ("pʰ",  "p"),   ("tʰ",  "t"),   ("kʰ",  "k"),
    # tltk uses c/cʰ for จ/ช (some IPA schemes use tɕ/tɕʰ — keep both)
    ("cʰ",  "ch"),  ("tɕʰ", "ch"),
    # Glottal stop (silent at word onset in Thai)
    ("ʔ",   ""),
    # Unaspirated simple (Paiboon+ uses bp/dt/g to signal unaspirated)
    ("b",   "b"),   ("p",   "bp"),
    ("d",   "d"),   ("t",   "dt"),
    ("k",   "g"),
    ("c",   "j"),   ("tɕ",  "j"),
    ("f",   "f"),   ("v",   "w"),
    ("s",   "s"),   ("h",   "h"),
    ("m",   "m"),   ("n",   "n"),   ("ŋ",   "ng"),
    ("l",   "l"),   ("r",   "r"),
    ("w",   "w"),   ("j",   "y"),
]

# ---------------------------------------------------------------------------
# Vowel nucleus (try longest pattern first).
# ᴐ (U+1D10) is tltk's non-standard glyph for /ɔ/.
# ---------------------------------------------------------------------------
_VOWELS: list[tuple[str, str]] = [
    # Diphthongs with long first vowel (must precede plain long vowels)
    ("iːa",  "ia"),
    ("ɯːa",  "eua"),
    ("uːa",  "ua"),
    # Long monophthongs
    ("aː",   "aa"),
    ("ɛː",   "aae"),
    ("eː",   "ee"),
    ("iː",   "ii"),
    ("ᴐː",   "oo"),   # tltk turned-o
    ("ɔː",   "oo"),   # standard IPA
    ("oː",   "oo"),
    ("ɯː",   "eu"),
    ("uː",   "uu"),
    ("ɤː",   "ooe"),
    # Short monophthongs
    ("a",    "a"),
    ("ɛ",    "ae"),
    ("e",    "e"),
    ("i",    "i"),
    ("ᴐ",    "o"),    # tltk turned-o
    ("ɔ",    "o"),    # standard IPA
    ("o",    "o"),
    ("ɯ",    "eu"),
    ("u",    "u"),
    ("ɤ",    "oe"),
]

# ---------------------------------------------------------------------------
# Coda consonants (try longest pattern first).
# ---------------------------------------------------------------------------
_CODAS: list[tuple[str, str]] = [
    ("ŋ",  "ng"),
    ("p",  "p"),  ("t",  "t"),  ("k",  "k"),
    ("m",  "m"),  ("n",  "n"),
    ("j",  "i"),  ("w",  "o"),
    ("ʔ",  ""),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _apply_tone(syllable: str, digit: str) -> str:
    """Insert the Paiboon+ tone diacritic after the first vowel letter."""
    combining = _TONE.get(digit, "")
    if not combining:
        return syllable
    for i, ch in enumerate(syllable):
        if ch in "aeiouAEIOU":
            return syllable[:i] + ch + combining + syllable[i + 1:]
    return syllable


def _match_first(s: str, table: list[tuple[str, str]]) -> tuple[str, str]:
    """
    Try each (ipa_pattern, paiboon_value) pair in *table* against the start
    of *s*.  Return (paiboon_value, remainder) for the first match, or
    ("", s) if nothing matches.
    """
    for ipa_pat, pb in table:
        if s.startswith(ipa_pat):
            return pb, s[len(ipa_pat):]
    return "", s


def _convert_syllable(raw: str) -> Optional[str]:
    """
    Convert a single tltk_ipa syllable string (including trailing tone digit)
    to a Paiboon+ string.  Returns None if the syllable cannot be parsed.
    """
    if not raw:
        return None

    # Extract trailing tone digit
    if raw[-1].isdigit():
        tone_digit = raw[-1]
        phonemes = raw[:-1]
    else:
        tone_digit = "1"   # default: mid tone
        phonemes = raw

    # --- onset ---
    onset_pb, phonemes = _match_first(phonemes, _ONSETS)
    # (onset_pb may be "" for a vowel-initial syllable or unknown onset)

    # --- vowel nucleus ---
    vowel_pb, phonemes = _match_first(phonemes, _VOWELS)
    if not vowel_pb:
        return None   # Cannot identify vowel; skip this syllable

    # --- coda (whatever's left) ---
    coda_pb, _ = _match_first(phonemes, _CODAS)

    syllable = onset_pb + vowel_pb + coda_pb
    return _apply_tone(syllable, tone_digit)


def _token_to_paiboon(thai_token: str) -> str:
    """Convert a single Thai word/token to Paiboon+ via tltk_ipa."""
    ipa_text = transliterate(thai_token, engine="tltk_ipa")
    if not ipa_text:
        return ""

    syllables = ipa_text.split(".")
    parts: list[str] = []
    for syl in syllables:
        syl = syl.strip()
        if syl:
            result = _convert_syllable(syl)
            parts.append(result if result is not None else syl)
    return "-".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def thai_to_paiboon(text: str) -> str:
    """
    Convert Thai script to Paiboon+ romanization.

    Tokenises *text* with PyThaiNLP word_tokenize (newmm engine), converts
    each Thai token through tltk_ipa → Paiboon+ mapping, and joins the
    results with spaces.

    Non-Thai tokens (Latin, digits, spaces) are passed through unchanged.

    Returns an empty string when PyThaiNLP is unavailable or conversion fails.
    """
    if not _PYTHAINLP_AVAILABLE:
        return ""

    text = text.strip()
    if not text:
        return ""
    text = expand_repetition_marks(text)

    try:
        tokens = word_tokenize(text, engine="newmm")
        parts: list[str] = []
        for token in tokens:
            if not any("\u0e00" <= ch <= "\u0e7f" for ch in token):
                if token.strip():
                    parts.append(token.strip())
                continue
            pb = _token_to_paiboon(token)
            if pb:
                parts.append(pb)
        return " ".join(parts)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# CLI helper  (python -m src.utils.paiboon <word1> <word2> ...)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    words = sys.argv[1:] if len(sys.argv) > 1 else [
        "สวัสดี", "กินข้าว", "คอมพิวเตอร์", "รถยนต์", "ประเทศไทย",
    ]
    for w in words:
        print(f"{w}  →  {thai_to_paiboon(w)}")
