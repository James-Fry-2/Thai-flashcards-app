"""Thai script → IPA romanization.

Reuses the tltk_ipa engine (same intermediate used by paiboon.py), strips the
trailing tone digit from each syllable, normalises the tltk non-standard
turned-o glyph (ᴐ U+1D10 → ɔ U+0254), and returns syllables joined by ".".

Returns an empty string on any failure so callers never crash.
"""
from src.utils.thai_repetition import expand_repetition_marks

try:
    from pythainlp.transliterate import transliterate
    from pythainlp.tokenize import word_tokenize
    _AVAILABLE = True
except ImportError:  # pragma: no cover
    _AVAILABLE = False


def thai_to_ipa(text: str) -> str:
    """Convert Thai script to IPA via tltk_ipa.

    Returns an empty string when PyThaiNLP is unavailable or conversion fails.
    """
    if not _AVAILABLE:
        return ""
    text = text.strip()
    if not text:
        return ""
    text = expand_repetition_marks(text)
    try:
        tokens = word_tokenize(text, engine="newmm")
        parts: list[str] = []
        for token in tokens:
            if not any("฀" <= ch <= "๿" for ch in token):
                if token.strip():
                    parts.append(token.strip())
                continue
            ipa_raw = transliterate(token, engine="tltk_ipa")
            if not ipa_raw:
                continue
            # Normalise tltk's non-standard turned-o to standard IPA
            ipa_raw = ipa_raw.replace("ᴐ", "ɔ")
            syllables = ipa_raw.split(".")
            cleaned: list[str] = []
            for syl in syllables:
                syl = syl.strip()
                if syl and syl[-1].isdigit():
                    syl = syl[:-1]
                if syl:
                    cleaned.append(syl)
            if cleaned:
                parts.append(".".join(cleaned))
        return " ".join(parts)
    except Exception:
        return ""
