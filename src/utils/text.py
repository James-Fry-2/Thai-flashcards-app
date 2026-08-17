"""Shared text utilities: edit distance and English gloss normalization."""
import re
import string

# Minimum stopword list for gloss content-word comparison (distractor validity guard).
STOPWORDS = {
    "to", "a", "an", "the", "of", "for", "in", "on", "be", "is", "or",
    "and", "some", "one",
}

_PUNCT_RE = re.compile(f"[{re.escape(string.punctuation)}]")


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for ca in a:
        curr = [prev[0] + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j] + (0 if ca == cb else 1), prev[j + 1] + 1, curr[j] + 1))
        prev = curr
    return prev[-1]


def normalize_gloss(s: str) -> str:
    """Lowercase, strip, collapse whitespace, strip punctuation, strip a leading 'to '."""
    s = _PUNCT_RE.sub(" ", (s or "").strip().lower())
    s = re.sub(r"\s+", " ", s).strip()
    if s.startswith("to "):
        s = s[3:]
    return s


def content_words(s: str) -> set[str]:
    """Normalized gloss split into words with stopwords removed."""
    return {w for w in normalize_gloss(s).split() if w and w not in STOPWORDS}
