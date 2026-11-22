"""
Lexicon-validated repair for Thai-script card fields (thai, example_thai).

The pure detection/normalisation lives in src.utils.text_integrity — this
module adds the one step that needs a database session: checking whether a
candidate U+FFFD repair is a real word before deciding whether it needs a
review flag (see decision 5 in the text-integrity design doc).
"""
from __future__ import annotations

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.services import lexicon_service
from src.utils.compound import _thai_word_set
from src.utils.text_integrity import IntegrityResult, _describe, _is_invalid_char, normalise_text

try:
    from pythainlp.tokenize import word_tokenize
except ImportError:  # pragma: no cover
    word_tokenize = None


def _is_thai_char(ch: str) -> bool:
    return "฀" <= ch <= "๿"


async def _is_real_word(db: AsyncSession, candidate: str) -> bool:
    if not candidate:
        return False
    if candidate in _thai_word_set():
        return True
    return bool(await lexicon_service.lookup(db, candidate))


async def repair_thai_field(
    db: AsyncSession, text: str, field: Literal["thai", "example_thai"]
) -> tuple[IntegrityResult, bool]:
    """Normalise *text*, and if U+FFFD is the only defect, repair it by
    removing the replacement character(s).

    Returns (result, validated):
    - No invalid characters at all -> (unchanged/normalised, True).
    - Invalid characters other than U+FFFD present (PUA, controls) -> the
      field is left as normalised-only (result.invalid_remaining is
      non-empty); validated is False and the caller does not treat this as
      a resolved repair (decision 7 — no auto-repair, flag as "invalid_chars").
    - Only U+FFFD present -> repaired by removing it; validated reflects
      whether the repaired text checks out against the Volubilis lexicon /
      pythainlp word list (decision 5).
    """
    original = text or ""
    normalized, repairs = normalise_text(original)

    bad_positions = [i for i, ch in enumerate(normalized) if _is_invalid_char(ch)]
    if not bad_positions:
        return (
            IntegrityResult(
                text=normalized, original=original,
                changed=normalized != original, repairs=repairs, invalid_remaining=[],
            ),
            True,
        )

    only_fffd = all(normalized[i] == "�" for i in bad_positions)
    if not only_fffd:
        remaining = [(i, _describe(ord(normalized[i]))) for i in bad_positions]
        return (
            IntegrityResult(
                text=normalized, original=original,
                changed=normalized != original, repairs=repairs, invalid_remaining=remaining,
            ),
            False,
        )

    candidate = normalized.replace("�", "")
    fffd_repairs = [f"removed U+FFFD at {i}" for i in bad_positions]

    if field == "thai":
        validated = await _is_real_word(db, candidate)
    elif word_tokenize is None:
        validated = False
    else:
        tokens = word_tokenize(candidate)
        thai_tokens = [t for t in tokens if any(_is_thai_char(c) for c in t)]
        validated = True
        for token in thai_tokens:
            if not await _is_real_word(db, token):
                validated = False
                break

    result = IntegrityResult(
        text=candidate, original=original, changed=True,
        repairs=repairs + fffd_repairs, invalid_remaining=[],
    )
    return result, validated
