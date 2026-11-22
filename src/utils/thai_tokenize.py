"""
Shared tokenisation for the romanization schemes (Paiboon+, RTGS, IPA).

newmm sometimes splits an orphan ห off from the syllable it silently modifies
(ห นำ), e.g. กะหลำปลี → ['กะ', 'ห', 'ลำ', 'ปลี']. Read alone, ห is the
syllable หอ ("hɔɔ"), so every downstream engine mis-romanises it as a
standalone "h" syllable instead of treating it as the high-class marker on
the following sonorant. Stripping ห instead of merging it would be wrong too:
ห นำ is what makes the syllable high class, so dropping it collapses the
tone (หมู "mǔu" would become มู "muu").
"""
from src.utils.thai_repetition import expand_repetition_marks

try:
    from pythainlp.tokenize import word_tokenize
    _AVAILABLE = True
except ImportError:  # pragma: no cover
    _AVAILABLE = False

HOR_HIP = "ห"

# Sonorant/semivowel-initial consonants that ห นำ can precede.
_SONORANT_STARTS = ("ง", "ญ", "น", "ม", "ย", "ร", "ล", "ว")


def merge_orphan_hor_nam(tokens: list[str]) -> list[str]:
    """
    Move an orphaned trailing/standalone ห onto the front of the following
    token when that token starts with a sonorant (ง ญ น ม ย ร ล ว).

    A bare ห token disappears into the next token; a token merely ending in
    ห (e.g. it is otherwise multi-character) has just its trailing ห moved
    across. Tokens before a non-sonorant token (e.g. หาย, already a single
    token) are left untouched.
    """
    merged: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        token = tokens[i]
        next_token = tokens[i + 1] if i + 1 < n else None
        if next_token and next_token[0] in _SONORANT_STARTS:
            if token == HOR_HIP:
                merged.append(HOR_HIP + next_token)
                i += 2
                continue
            if len(token) > 1 and token.endswith(HOR_HIP):
                merged.append(token[:-1])
                merged.append(HOR_HIP + next_token)
                i += 2
                continue
        merged.append(token)
        i += 1
    return merged


def romanization_tokens(text: str) -> list[str]:
    """
    Tokenise *text* for all romanization schemes: expand ๆ, run newmm
    word_tokenize, drop empty/whitespace tokens, then merge orphan ห นำ.
    """
    text = expand_repetition_marks(text)
    raw_tokens = word_tokenize(text, engine="newmm")
    tokens = [t for t in raw_tokens if t.strip()]
    return merge_orphan_hor_nam(tokens)
