"""
Deterministic confusable-pair detection: phonetic (IPA), orthographic (Thai
script), and tone signals. No LLM, no embeddings — surface-similarity only,
distinct from the semantic "related" suggestion path.

`romanization_ipa` (src/utils/ipa_romanization.py) already strips the tltk
tone digit, so it doubles as the tone-agnostic segmental skeleton: two cards
with identical IPA but different `tone_pattern` are the classic Thai tone
minimal pair (e.g. เสือ "tiger" vs เสื้อ "shirt").
"""
from __future__ import annotations

from typing import Optional, TypedDict

from src.config.settings import Settings


class ConfusableCard(TypedDict, total=False):
    thai: str
    romanization_ipa: Optional[str]
    tone_pattern: Optional[list[str]]


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                prev[j] + 1,       # deletion
                curr[j - 1] + 1,   # insertion
                prev[j - 1] + cost,  # substitution
            )
        prev = curr
    return prev[-1]


def orthographic_distance(a_thai: str, b_thai: str) -> int:
    """Levenshtein distance on the Thai script strings."""
    return _levenshtein(a_thai or "", b_thai or "")


def phonetic_distance(a_ipa: str, b_ipa: str) -> float:
    """Levenshtein distance on IPA strings, normalized by the longer string's length."""
    a_ipa = a_ipa or ""
    b_ipa = b_ipa or ""
    max_len = max(len(a_ipa), len(b_ipa))
    if max_len == 0:
        return 0.0
    return _levenshtein(a_ipa, b_ipa) / max_len


def _is_tone_pair(
    a_ipa: Optional[str],
    a_tone_pattern: Optional[list[str]],
    b_ipa: Optional[str],
    b_tone_pattern: Optional[list[str]],
) -> bool:
    """Segmental skeletons (tone-stripped IPA) match, but tone patterns differ."""
    if not a_ipa or not b_ipa or not a_tone_pattern or not b_tone_pattern:
        return False
    if a_ipa != b_ipa:
        return False
    return a_tone_pattern != b_tone_pattern


def is_confusable(a: ConfusableCard, b: ConfusableCard, settings: Settings) -> Optional[str]:
    """
    Return the detection reason ("phonetic", "orthographic", "tone", or a
    "+"-joined combination) if `a` and `b` are confusable, else None.
    """
    a_thai, b_thai = a.get("thai") or "", b.get("thai") or ""
    if len(a_thai) < settings.confusable_min_length or len(b_thai) < settings.confusable_min_length:
        return None
    if a_thai == b_thai:
        # Same word — a duplicate, not a different-word confusable pair.
        return None

    reasons: list[str] = []

    a_ipa, b_ipa = a.get("romanization_ipa"), b.get("romanization_ipa")
    if a_ipa and b_ipa and phonetic_distance(a_ipa, b_ipa) <= settings.confusable_max_phonetic:
        reasons.append("phonetic")

    if orthographic_distance(a_thai, b_thai) <= settings.confusable_max_orthographic:
        reasons.append("orthographic")

    if _is_tone_pair(a_ipa, a.get("tone_pattern"), b_ipa, b.get("tone_pattern")):
        reasons.append("tone")

    if not reasons:
        return None
    return "+".join(reasons)


def _bigrams(text: str) -> set[str]:
    return {text[i:i + 2] for i in range(len(text) - 1)}


def generate_candidate_pairs(cards: list[ConfusableCard]) -> set[tuple[int, int]]:
    """
    Block candidate pairs via inverted bigram indexes over Thai script and IPA
    — the same shared-bigram technique as
    link_suggestion_service._rank_candidates_bigram, indexed both ways since
    we're pairing many cards rather than ranking candidates against one
    target. Avoids scoring all O(n^2) pairs.

    A pair of indexes into `cards` is a candidate if the two cards share >=1
    Thai bigram or >=1 IPA bigram, and their Thai lengths differ by <=2.
    """
    thai_index: dict[str, list[int]] = {}
    ipa_index: dict[str, list[int]] = {}
    for idx, card in enumerate(cards):
        for bg in _bigrams(card.get("thai") or ""):
            thai_index.setdefault(bg, []).append(idx)
        for bg in _bigrams(card.get("romanization_ipa") or ""):
            ipa_index.setdefault(bg, []).append(idx)

    pairs: set[tuple[int, int]] = set()
    for index in (thai_index, ipa_index):
        for indexes in index.values():
            for i in range(len(indexes)):
                for j in range(i + 1, len(indexes)):
                    a_idx, b_idx = indexes[i], indexes[j]
                    a_len = len(cards[a_idx].get("thai") or "")
                    b_len = len(cards[b_idx].get("thai") or "")
                    if abs(a_len - b_len) <= 2:
                        pairs.add((min(a_idx, b_idx), max(a_idx, b_idx)))
    return pairs
