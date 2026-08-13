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
    from sqlalchemy import select
    from src.db.models.card import Card
    from src.db.services import lexicon_service
    from src.utils.paiboon import thai_to_paiboon

    result = []
    for part in parts:
        romanization = thai_to_paiboon(part) or None

        # Step 1: own cards
        gloss: str | None = None
        gloss_source: str | None = None
        try:
            existing = await db.scalar(
                select(Card.english).where(Card.thai == part).limit(1)
            )
            if existing:
                gloss = existing
                gloss_source = "card"
        except Exception:
            pass

        # Step 2: closed-set bound-morpheme map
        if gloss is None and part in _MORPHEME_GLOSS:
            gloss = _MORPHEME_GLOSS[part]
            gloss_source = "morpheme"

        # Step 3: Volubilis lexicon
        if gloss is None:
            try:
                translations = await lexicon_service.lookup(db, part)
            except Exception:
                translations = []
            if translations:
                gloss = translations[0]
                gloss_source = "volubilis"

        # Step 4: PyThaiNLP OMW wordnet
        if gloss is None:
            gloss, gloss_source = _wordnet_gloss(part)

        result.append({
            "thai": part,
            "romanization": romanization,
            "gloss": gloss,
            "gloss_source": gloss_source,
        })

    return result


def _wordnet_gloss(thai_word: str) -> tuple[str | None, str | None]:
    """Return (gloss, "lexicon") from OMW Thai wordnet, or (None, None)."""
    try:
        from pythainlp.corpus import wordnet as wn
        synsets = wn.synsets(thai_word, lang="tha")
        if not synsets:
            return None, None
        # Use the first English lemma name from the first synset
        for synset in synsets:
            lemmas = synset.lemma_names("eng")
            if lemmas:
                # Clean up underscores used in wordnet lemma names
                return lemmas[0].replace("_", " "), "lexicon"
        return None, None
    except Exception:
        return None, None


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
