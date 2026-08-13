"""
Cross-check a card's English translation against the shared Volubilis lexicon.

Advisory only: the source-material translation is always authoritative. This
module never changes `english` — it only classifies whether the material
value looks consistent with the lexicon, so the caller can flag cards for
user review.

Purely lexical for now (token-set overlap). An embedding or LLM second
opinion could tighten false-positive avoidance further — not built here.
"""
from __future__ import annotations

import re
import string
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_STOP = {"a", "an", "the", "to", "of", "some", "any"}

_PUNCT_RE = re.compile(f"[{re.escape(string.punctuation)}]")


def _content_tokens(s: str) -> set[str]:
    s = _PUNCT_RE.sub(" ", (s or "").lower())
    return {tok for tok in s.split() if tok and tok not in _STOP}


async def check_translation(
    db: "AsyncSession", thai: str, english: str
) -> tuple[str, list[str] | None]:
    """
    Returns (status, candidates).

    - No lexicon entries for `thai`                        -> ('unverified', None)
    - `english` shares >=1 content token with any lexicon
      translation                                           -> ('ok', None)
    - Lexicon has entries but zero content-token overlap    -> ('flagged', top ~5 distinct translations)
    """
    from src.db.services import lexicon_service

    translations = await lexicon_service.lookup(db, thai)
    if not translations:
        return "unverified", None

    english_tokens = _content_tokens(english)
    for translation in translations:
        if english_tokens & _content_tokens(translation):
            return "ok", None

    return "flagged", translations[:5]
