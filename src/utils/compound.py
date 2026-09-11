"""
Thai compound-word decomposition and gloss resolution.

decompose(thai)         -> list[str] | None
    Segment a Thai string into 2+ dictionary constituents using greedy
    longest-match DP over pythainlp.corpus.thai_words().  Returns None
    when the word is atomic, a single syllable, a loanword, or decomposition
    cannot achieve full dictionary coverage.

resolve_glosses(db, parts) -> list[dict]  (async)
    For each constituent, resolve a gloss via:
      1. Own-cards lookup (cards.thai index, gloss_source="card")
      2. Closed-set bound-morpheme map (gloss_source="morpheme")
      3. Volubilis lexicon table (gloss_source="volubilis")
      4. PyThaiNLP Open Multilingual WordNet Thai (gloss_source="lexicon")
      LLM fallback (step 5) is handled separately by the caller when
      compound_gloss_llm_fallback is enabled.

Both functions are pure/deterministic and degrade gracefully (return None /
empty list) if PyThaiNLP is unavailable.

Licensing note: The OMW Thai data bundled with PyThaiNLP wordnet is
distributed under CC-BY 4.0 (Thai National Corpus / OMW-TH) — compatible
with bundling in this application.
"""
from __future__ import annotations

import functools
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Thai word corpus — loaded once and cached
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _thai_word_set() -> frozenset[str]:
    try:
        from pythainlp.corpus import thai_words
        return frozenset(thai_words())
    except Exception:
        return frozenset()


# ---------------------------------------------------------------------------
# Decomposition
# ---------------------------------------------------------------------------

def decompose(thai: str) -> list[str] | None:
    """
    Segment *thai* into 2+ dictionary constituents.

    Uses greedy longest-match DP (left to right).  Prefers fewer, longer
    components because the greedy approach naturally picks the longest
    dictionary match at each position.

    Returns None when:
    - The string cannot be fully covered by ≥2 dictionary words
    - The only covering segmentation is the whole word itself
    - The string is empty or non-Thai
    - PyThaiNLP is unavailable
    """
    try:
        return _decompose_inner(thai)
    except Exception:
        return None


def _decompose_inner(thai: str) -> list[str] | None:
    thai = (thai or "").strip()
    if not thai:
        return None

    # Require at least one Thai character
    if not any("฀" <= ch <= "๿" for ch in thai):
        return None

    words = _thai_word_set()
    if not words:
        return None

    n = len(thai)

    # Minimum-parts DP — seeks a segmentation into ≥2 dictionary words, each a
    # proper substring of the whole input (whole-word segment is explicitly excluded).
    # Prefers fewer parts (longest components) by trying the smallest j first at
    # each end-position i, and keeping only strictly-better (fewer-parts) updates.
    INF = float("inf")
    min_parts: list[float] = [INF] * (n + 1)
    min_parts[0] = 0.0
    best_parent: list[int] = [-1] * (n + 1)

    max_parts = 3  # mirrors compound_max_syllables intent; catches NULL-syllable-count cards
    for i in range(1, n + 1):
        # Smallest j first → longest segment thai[j:i] considered first.
        # Skip j==0,i==n: that segment is the whole word itself.
        for j in range(max(0, i - 30), i):
            if j == 0 and i == n:
                continue  # exclude whole-word self-match
            if min_parts[j] < INF and thai[j:i] in words:
                candidate = min_parts[j] + 1
                if candidate > max_parts:
                    continue  # prune: more parts than allowed
                if candidate < min_parts[i]:
                    min_parts[i] = candidate
                    best_parent[i] = j

    if min_parts[n] == INF or min_parts[n] < 2:
        return None

    # Reconstruct the minimum-parts segmentation
    parts: list[str] = []
    pos = n
    while pos > 0:
        prev = best_parent[pos]
        if prev == -1:
            return None  # reconstruction error
        parts.append(thai[prev:pos])
        pos = prev
    parts.reverse()

    if len(parts) < 2:
        return None

    return parts


# ---------------------------------------------------------------------------
# Full segmentation enumeration — for the user-correction candidate list.
# Independent of decompose()'s min-parts DP: this returns every valid
# dictionary segmentation (including the whole-word single-part option),
# not just the preferred one.
# ---------------------------------------------------------------------------

# Hard cap on segmentations explored during backtracking, independent of the
# caller's `limit` — bounds worst-case work for inputs where many short
# dictionary words match at every position, without needing memoization.
_MAX_SEGMENTATIONS_EXPLORED = 2000


def enumerate_segmentations(thai: str, limit: int = 8) -> list[list[str]]:
    """
    Return every valid dictionary segmentation of *thai*, most-preferred
    first: ascending part count, then descending length of the first part.
    Includes the whole-word single-part segmentation when *thai* itself is a
    dictionary entry (the "actually not a compound" candidate — distinct
    from suppression, which has no segmentation at all).

    Pure enumeration — does not share state with decompose() and never
    raises; returns [] on any failure or when the corpus is unavailable.
    """
    try:
        return _enumerate_segmentations_inner(thai, limit)
    except Exception:
        return []


def _enumerate_segmentations_inner(thai: str, limit: int) -> list[list[str]]:
    thai = (thai or "").strip()
    if not thai:
        return []

    words = _thai_word_set()
    if not words:
        return []

    n = len(thai)
    found: list[list[str]] = []

    def backtrack(pos: int, current: list[str]) -> None:
        if len(found) >= _MAX_SEGMENTATIONS_EXPLORED:
            return
        if pos == n:
            found.append(list(current))
            return
        for end in range(n, pos, -1):  # longest substring first
            if len(found) >= _MAX_SEGMENTATIONS_EXPLORED:
                return
            segment = thai[pos:end]
            if segment in words:
                current.append(segment)
                backtrack(end, current)
                current.pop()

    backtrack(0, [])

    found.sort(key=lambda parts: (len(parts), -len(parts[0])))
    return found[:limit]


# ---------------------------------------------------------------------------
# Closed-set bound morphemes / nominalizers wordnet won't gloss. Functional glosses.
# ---------------------------------------------------------------------------

_MORPHEME_GLOSS: dict[str, str] = {
    "การ": "act of / -ing",
    "ความ": "-ness (abstract noun)",
    "ผู้": "person who / -er",
    "นัก": "-ist / habitual doer",
    "ช่าง": "craftsman / -smith",
    "เครื่อง": "machine / device",
    "ชาว": "people of / folk",
    "น่า": "-worthy",
    "ที่": "place / -er",
}


# ---------------------------------------------------------------------------
# Gloss sense selection — dictionary sources (Volubilis, wordnet) return
# translations in an arbitrary/lexicographic order, not by commonness, so the
# first entry is often a rare or technical sense (e.g. a scientific binomial).
# ---------------------------------------------------------------------------

_TWO_WORD_CAPITALIZED_RE = re.compile(r"^[A-Z][a-z]+\s+[a-z]+$")

# zipf_frequency is a log-scale word commonness score (~1-8 for real English
# words, 0 for words absent from the corpus entirely). Latin species epithets
# like "gigantea" occasionally show up with a tiny nonzero score (incidental
# corpus mentions), so binomial detection uses a low-end cutoff rather than
# requiring exactly 0 — ordinary English words like "crown"/"flower" score
# well above it (~4+).
_UNKNOWN_WORD_ZIPF_CUTOFF = 2.5


def _word_freq(word: str) -> float:
    try:
        from wordfreq import zipf_frequency
        return zipf_frequency(word.lower(), "en")
    except Exception:
        return 0.0


def _is_binomial(candidate: str) -> bool:
    """True for scientific-binomial-shaped candidates ("Calotropis gigantea")
    where neither word is recognized English. The capitalized+lowercase shape
    alone isn't enough to tell apart a real binomial from an ordinary
    two-word gloss like "Crown flower" (both real English words) — checking
    that both tokens are otherwise-unknown to English word frequency data is
    what distinguishes them."""
    match = _TWO_WORD_CAPITALIZED_RE.match(candidate.strip())
    if not match:
        return False
    genus, species = candidate.strip().split()
    return (
        _word_freq(genus) < _UNKNOWN_WORD_ZIPF_CUTOFF
        and _word_freq(species) < _UNKNOWN_WORD_ZIPF_CUTOFF
    )


# Thai kinship/body terms (พี่, น้อง, ตัว, ...) double as first/second-person
# pronouns in casual speech, so Volubilis genuinely lists "I"/"you" as a
# sense — but personal pronouns are near-universally the single
# highest-frequency English word for any Thai word that has one as a sense,
# so pure frequency ranking always promotes it above the word's dominant
# sense in a compound (พี่สาว = "elder sister", never "I sister"). Excluded
# the same way binomials are: from the ranking candidate pool, not by
# special-casing specific Thai words. Deliberately excludes "one" — it's a
# real, correct gloss for numeral compounds (หนึ่งทุ่ม "one" + "o'clock").
_BARE_PRONOUNS = frozenset({
    "i", "you", "he", "she", "it", "we", "they",
    "me", "him", "her", "us", "them",
})


def _is_bare_pronoun(candidate: str) -> bool:
    """True when *candidate* is nothing but a personal pronoun. A qualified
    variant like "you (to s.o. older, inf.)" is a different string and is
    NOT excluded — only an exact bare pronoun match is."""
    return candidate.strip().lower() in _BARE_PRONOUNS


# Function words to skip when scoring a multi-word gloss like "be fond of" —
# they're extremely high-frequency themselves ("be", "of") but aren't the
# word that carries the sense, so scoring by them (or by just the first
# word) would rank glossary filler above single content words like "love".
_STOPWORDS = frozenset({
    "a", "an", "the", "to", "of", "on", "in", "at", "for", "with", "and", "or",
    "be", "is", "am", "are", "was", "were", "been", "being",
})


def _gloss_freq_score(candidate: str) -> float:
    words = candidate.strip().lower().split()
    content_words = [w for w in words if w not in _STOPWORDS] or words
    return max((_word_freq(w) for w in content_words), default=0.0)


def _ranked_by_frequency(candidates: list[str]) -> list[str]:
    """*candidates* sorted by English word-frequency score, descending; ties
    keep their original relative order (Python's sort is stable), so the
    first element always equals pick_best_gloss's selection over the same
    list. Used both to implement pick_best_gloss and to expose the full
    ranked candidate list for the compound-candidates endpoint."""
    return sorted(candidates, key=lambda c: -_gloss_freq_score(c))


def pick_best_gloss(translations: list[str]) -> str | None:
    """Choose the everyday sense from an ordered list of translations.

    Drops scientific binomials and bare personal pronouns, then ranks the
    rest by English word frequency and returns the most common. Falls back
    to the first remaining entry if no candidate has frequency data; None if
    the list is empty or every entry was dropped.
    """
    candidates = [
        t for t in translations
        if t and not _is_binomial(t) and not _is_bare_pronoun(t)
    ]
    if not candidates:
        return None
    return _ranked_by_frequency(candidates)[0]


# Volubilis Level marker ordering: B (basic) < A1 (intermediate) < A2
# (advanced) < s (special); anything else (including NULL / unrecognized)
# sorts last.
_LEVEL_ORDER: dict[str, int] = {"B": 0, "A1": 1, "A2": 2, "s": 3}


def _ranked_volubilis_glosses(senses: list[dict]) -> list[str]:
    """Full ranked candidate list behind select_gloss_by_level: Level tier
    first (B < A1 < A2 < s, NULL last), frequency as the tie-break within a
    tier. First element always equals select_gloss_by_level's selection."""
    candidates = [
        s for s in senses
        if s.get("english") and not _is_binomial(s["english"]) and not _is_bare_pronoun(s["english"])
    ]
    if not candidates:
        return []

    if all(s.get("level") is None for s in candidates):
        return _ranked_by_frequency([s["english"] for s in candidates])

    tiers = sorted({_LEVEL_ORDER.get(s.get("level"), 99) for s in candidates})
    ordered: list[str] = []
    for tier in tiers:
        tier_glosses = [
            s["english"] for s in candidates
            if _LEVEL_ORDER.get(s.get("level"), 99) == tier
        ]
        ordered.extend(tier_glosses if len(tier_glosses) == 1 else _ranked_by_frequency(tier_glosses))
    return ordered


def select_gloss_by_level(senses: list[dict]) -> str | None:
    """Choose the everyday sense from an ordered list of {english, level, ...}
    dicts, using the Volubilis Level marker as the primary rank (B < A1 < A2
    < s, NULL last) and pick_best_gloss's frequency ranking as the tie-break
    within a level.

    Scientific binomials are dropped first, same as pick_best_gloss. When
    every surviving sense has a NULL level (the source file carries no level
    data for this entry), this degrades to plain pick_best_gloss ranking —
    identical to the pre-Level behaviour.
    """
    ranked = _ranked_volubilis_glosses(senses)
    return ranked[0] if ranked else None


# ---------------------------------------------------------------------------
# Gloss resolution ladder (steps 1-4; step 5, the LLM fallback, is caller-side)
# ---------------------------------------------------------------------------

async def resolve_glosses(
    db: "AsyncSession",
    parts: list[str],
) -> list[dict]:
    """
    Return a list of part-dicts: {thai, romanization, gloss, gloss_source}.

    gloss and gloss_source are None when none of own-cards, the morpheme map,
    the Volubilis lexicon, or wordnet resolved a gloss for that part.  The
    LLM fallback (step 5) must be applied by the caller after this function
    returns, if needed.
    """
    from src.utils.paiboon import thai_to_paiboon

    result = []
    for part in parts:
        romanization = thai_to_paiboon(part) or None
        candidates = await gloss_candidates(db, part)
        top = candidates[0] if candidates else None
        result.append({
            "thai": part,
            "romanization": romanization,
            "gloss": top["gloss"] if top else None,
            "gloss_source": top["source"] if top else None,
        })

    return result


async def gloss_candidates(db: "AsyncSession", thai_part: str) -> list[dict]:
    """
    All distinct gloss candidates for one compound part, across every ladder
    source, each tagged {gloss, source}, in the same priority order the
    ladder consults them (own cards -> morpheme map -> Volubilis -> wordnet).
    Deduplicated case-insensitively and capped at 8.

    resolve_glosses() takes this list's first entry as its selection, which
    is exactly what the un-refactored step-by-step ladder picked — this
    function only makes the sources the ladder *would have* discarded
    visible, for the compound-correction candidate UI.
    """
    from sqlalchemy import select
    from src.db.models.card import Card
    from src.db.services import lexicon_service

    raw: list[dict] = []

    # Step 1: own cards
    try:
        existing = await db.scalar(
            select(Card.english).where(Card.thai == thai_part).limit(1)
        )
        if existing:
            raw.append({"gloss": existing, "source": "card"})
    except Exception:
        pass

    # Step 2: closed-set bound-morpheme map
    if thai_part in _MORPHEME_GLOSS:
        raw.append({"gloss": _MORPHEME_GLOSS[thai_part], "source": "morpheme"})

    # Step 3: Volubilis lexicon
    try:
        senses = await lexicon_service.lookup_ranked(db, thai_part)
    except Exception:
        senses = []
    for gloss in _ranked_volubilis_glosses(senses):
        raw.append({"gloss": gloss, "source": "volubilis"})

    # Step 4: PyThaiNLP OMW wordnet. Goes through _wordnet_gloss (not
    # _wordnet_gloss_candidates directly) for its top pick first — that's
    # the ladder's actual step-4 call, and resolve_glosses' existing unit
    # tests patch it directly. The full ranked list is merged in after;
    # dedup below keeps the top pick's rank if the two agree.
    top_gloss, top_source = _wordnet_gloss(thai_part)
    if top_gloss is not None:
        raw.append({"gloss": top_gloss, "source": top_source})
    for gloss in _wordnet_gloss_candidates(thai_part):
        raw.append({"gloss": gloss, "source": "lexicon"})

    seen: set[str] = set()
    deduped: list[dict] = []
    for c in raw:
        key = c["gloss"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
        if len(deduped) >= 8:
            break
    return deduped


def _wordnet_gloss_candidates(thai_word: str) -> list[str]:
    """Ranked, non-binomial lemma candidates from OMW Thai wordnet. First
    element always equals _wordnet_gloss's selection."""
    try:
        from pythainlp.corpus import wordnet as wn
        synsets = wn.synsets(thai_word, lang="tha")
        if not synsets:
            return []
        # Collect lemma candidates across the first few synsets — synset
        # order isn't ranked by commonness, so limiting to synsets[0] risked
        # a rare/technical sense the same way the Volubilis step did.
        candidates: list[str] = []
        seen: set[str] = set()
        for synset in synsets[:5]:
            for lemma in synset.lemma_names("eng"):
                cleaned = lemma.replace("_", " ")
                if cleaned not in seen:
                    seen.add(cleaned)
                    candidates.append(cleaned)
        non_binomial = [c for c in candidates if not _is_binomial(c) and not _is_bare_pronoun(c)]
        return _ranked_by_frequency(non_binomial) if non_binomial else []
    except Exception:
        return []


def _wordnet_gloss(thai_word: str) -> tuple[str | None, str | None]:
    """Return (gloss, "lexicon") from OMW Thai wordnet, or (None, None)."""
    candidates = _wordnet_gloss_candidates(thai_word)
    return (candidates[0], "lexicon") if candidates else (None, None)


# ---------------------------------------------------------------------------
# High-level helper used by create_card and the backfill script
# ---------------------------------------------------------------------------

async def compute_compound_breakdown(
    db: "AsyncSession",
    thai: str,
    syllable_count: int | None = None,
) -> tuple[list[dict] | None, bool | None]:
    """
    Returns (breakdown, is_compound).

    is_compound is a structural signal: True whenever decompose() finds ≥2
    dictionary constituents, regardless of gloss coverage; False when
    decompose() returned None or the syllable cap is exceeded.

    breakdown is the learner-facing surfaced hint, which is a separate,
    stricter concern (the surface guard). It is None when:
    - The word exceeds compound_max_syllables (treated as not a compound)
    - The word isn't a resolvable compound
    - Decomposition succeeds but the fraction of parts that resolve a gloss
      falls below compound_surface_min_gloss_ratio (default 1.0 — every
      part must gloss for the breakdown to surface)
    """
    from src.config.settings import get_settings
    settings = get_settings()
    max_syl = settings.compound_max_syllables
    if syllable_count is not None and syllable_count > max_syl:
        return None, False

    parts = decompose(thai)
    if parts is None:
        return None, False

    resolved = await resolve_glosses(db, parts)
    glossed = sum(1 for p in resolved if p["gloss"])
    ratio = glossed / len(resolved) if resolved else 0.0
    surfaced = ratio >= settings.compound_surface_min_gloss_ratio
    return (resolved if surfaced else None), True
