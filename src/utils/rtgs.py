"""
Thai script → RTGS (Royal Thai General System) romanization.

Derived from tltk_ipa syllables (the same intermediate used by paiboon.py),
mapped through onset/vowel/coda tables — not from pythainlp's 'royin' engine,
which mis-romanises ร/ล as "n" and reads a lone ห นำ as its own "h" syllable
(see issue #1). RTGS is toneless and does not distinguish vowel length, so
long and short vowels collapse to the same letters and the tone digit is
simply dropped.

Falls back to 'royin' for any syllable tltk_ipa can't parse, so a token never
comes back as a partial/garbled string.

Returns an empty string on any failure so callers never crash.
"""
from typing import Optional

from src.utils.thai_tokenize import romanization_tokens

try:
    from pythainlp.transliterate import transliterate, romanize as _romanize
    _AVAILABLE = True
except ImportError:  # pragma: no cover
    _AVAILABLE = False

# ---------------------------------------------------------------------------
# Onset consonants (try longest pattern first).
# tltk_ipa uses ʰ (U+02B0) to mark aspiration.
# ---------------------------------------------------------------------------
_ONSETS: list[tuple[str, str]] = [
    # Clusters — aspirated
    ("pʰr", "phr"), ("pʰl", "phl"),
    ("kʰw", "khw"), ("kʰr", "khr"), ("kʰl", "khl"),
    ("tɕʰ", "ch"),
    # Clusters — unaspirated
    ("pr", "pr"), ("pl", "pl"),
    ("kr", "kr"), ("kl", "kl"), ("kw", "kw"),
    ("tr", "tr"),
    # Aspirated simple
    ("pʰ", "ph"), ("tʰ", "th"), ("kʰ", "kh"),
    ("cʰ", "ch"), ("tɕ", "ch"),
    # Glottal stop (silent at word onset in Thai)
    ("ʔ", ""),
    ("ŋ", "ng"), ("j", "y"), ("v", "w"),
    ("b", "b"), ("p", "p"), ("d", "d"), ("t", "t"), ("k", "k"),
    ("f", "f"), ("s", "s"), ("h", "h"),
    ("m", "m"), ("n", "n"), ("l", "l"), ("r", "r"), ("w", "w"),
    ("c", "ch"),
]

# ---------------------------------------------------------------------------
# Vowel nucleus (try longest pattern first). Long/short collapse; RTGS carries
# no vowel-length marking. ᴐ (U+1D10) is tltk's non-standard glyph for /ɔ/.
# ---------------------------------------------------------------------------
_VOWELS: list[tuple[str, str]] = [
    ("iːa", "ia"), ("ɯːa", "uea"), ("uːa", "ua"),
    ("ia", "ia"), ("ɯa", "uea"), ("ua", "ua"),
    ("aː", "a"), ("ɛː", "ae"), ("eː", "e"), ("iː", "i"),
    ("ɔː", "o"), ("ᴐː", "o"), ("oː", "o"),
    ("ɯː", "ue"), ("uː", "u"), ("ɤː", "oe"),
    ("a", "a"), ("ɛ", "ae"), ("e", "e"), ("i", "i"),
    ("ɔ", "o"), ("ᴐ", "o"), ("o", "o"),
    ("ɯ", "ue"), ("u", "u"), ("ɤ", "oe"),
]

# ---------------------------------------------------------------------------
# Coda consonants (try longest pattern first).
# ---------------------------------------------------------------------------
_CODAS: list[tuple[str, str]] = [
    ("ŋ", "ng"),
    ("p", "p"), ("t", "t"), ("k", "k"),
    ("m", "m"), ("n", "n"),
    ("j", "i"), ("w", "o"),
    ("ʔ", ""),
]


def _match_first(s: str, table: list[tuple[str, str]]) -> tuple[str, str]:
    """Try each (ipa_pattern, rtgs_value) pair against the start of *s*."""
    for ipa_pat, rtgs in table:
        if s.startswith(ipa_pat):
            return rtgs, s[len(ipa_pat):]
    return "", s


def _convert_syllable(raw: str) -> Optional[str]:
    """Convert a single tltk_ipa syllable (with trailing tone digit) to RTGS."""
    if not raw:
        return None

    phonemes = raw[:-1] if raw[-1].isdigit() else raw

    onset_r, phonemes = _match_first(phonemes, _ONSETS)
    vowel_r, phonemes = _match_first(phonemes, _VOWELS)
    if not vowel_r:
        return None
    coda_r, _ = _match_first(phonemes, _CODAS)

    return onset_r + vowel_r + coda_r


def _fallback(token: str) -> str:
    try:
        return _romanize(token, engine="royin") or ""
    except Exception:
        return ""


def _token_to_rtgs(thai_token: str) -> str:
    """Convert a single Thai word/token to RTGS via tltk_ipa, else 'royin'."""
    ipa_text = transliterate(thai_token, engine="tltk_ipa")
    if not ipa_text:
        return _fallback(thai_token)

    parts: list[str] = []
    for syl in ipa_text.split("."):
        syl = syl.strip()
        if not syl:
            continue
        result = _convert_syllable(syl)
        if result is None:
            return _fallback(thai_token)
        parts.append(result)

    return "".join(parts) if parts else _fallback(thai_token)


def thai_to_rtgs(text: str) -> str:
    """Convert Thai script to RTGS romanization.

    Returns an empty string when PyThaiNLP is unavailable or conversion fails.
    """
    if not _AVAILABLE:
        return ""
    text = text.strip()
    if not text:
        return ""

    try:
        tokens = romanization_tokens(text)
        parts: list[str] = []
        for token in tokens:
            if not any("฀" <= ch <= "๿" for ch in token):
                if token.strip():
                    parts.append(token.strip())
                continue
            rtgs = _token_to_rtgs(token)
            if rtgs:
                parts.append(rtgs)
        return " ".join(parts)
    except Exception:
        return ""
