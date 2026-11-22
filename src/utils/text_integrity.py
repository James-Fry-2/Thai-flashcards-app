"""
Deterministic text-integrity checks for card content — catches the character
corruption a broken PDF font ToUnicode CMap leaves behind (PyMuPDF emits
U+FFFD for glyphs it can't map) before it reaches romanization/generation.

No DB or LLM calls here — see src/db/services/text_integrity_service.py for
the lexicon-validated Thai repair, which needs a database session.

find_invalid_chars(text)     -> [(index, "U+XXXX NAME"), ...]
normalise_text(text)         -> (text, repairs)   deterministic normalisation only
repair_non_thai_field(text)  -> IntegrityResult    strips invalid chars, no validation
count_replacement_chars(text) -> int
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Zero-width characters + soft hyphen, stripped unconditionally.
_ZERO_WIDTH = {"​", "‌", "‍", "﻿", "­"}

# Nikhahit + optional tone mark + sara aa -> tone mark (if any) + sara am.
_SARA_AM_RE = re.compile("ํ([่-๋]?)า")
_SARA_AM = "ำ"

_WHITESPACE_RUN_RE = re.compile(r" {2,}")


@dataclass
class IntegrityResult:
    text: str                 # normalised / repaired value
    original: str
    changed: bool
    repairs: list[str] = field(default_factory=list)
    invalid_remaining: list[tuple[int, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Invalid-character detection (decision 3)
# ---------------------------------------------------------------------------

def _is_noncharacter(cp: int) -> bool:
    if 0xFDD0 <= cp <= 0xFDEF:
        return True
    return (cp & 0xFFFE) == 0xFFFE


def _is_invalid_char(ch: str) -> bool:
    cp = ord(ch)
    if cp == 0xFFFD:
        return True
    if 0xE000 <= cp <= 0xF8FF:
        return True
    if cp < 0x20 and ch not in ("\n", "\t"):
        return True
    if 0x80 <= cp <= 0x9F:
        return True
    return _is_noncharacter(cp)


def _describe(cp: int) -> str:
    if cp == 0xFFFD:
        label = "REPLACEMENT CHARACTER"
    elif 0xE000 <= cp <= 0xF8FF:
        label = "PRIVATE USE"
    elif cp < 0x20 or 0x80 <= cp <= 0x9F:
        label = "CONTROL"
    elif _is_noncharacter(cp):
        label = "NONCHARACTER"
    else:
        try:
            label = unicodedata.name(chr(cp))
        except ValueError:
            label = "UNASSIGNED"
    return f"U+{cp:04X} {label}"


def find_invalid_chars(text: str) -> list[tuple[int, str]]:
    """Indices + human-readable names of every invalid code point in *text*."""
    return [(i, _describe(ord(ch))) for i, ch in enumerate(text or "") if _is_invalid_char(ch)]


def count_replacement_chars(text: str) -> int:
    return (text or "").count("�")


# ---------------------------------------------------------------------------
# Deterministic normalisation (decision 4)
# ---------------------------------------------------------------------------

def normalise_text(text: str) -> tuple[str, list[str]]:
    """NFC + strip zero-width/soft-hyphen chars + recompose decomposed sara am.

    Pure and idempotent — running it twice on its own output is a no-op.
    """
    text = text or ""
    repairs: list[str] = []

    nfc = unicodedata.normalize("NFC", text)
    if nfc != text:
        repairs.append("applied NFC normalization")
    text = nfc

    if any(ch in _ZERO_WIDTH for ch in text):
        out = []
        for i, ch in enumerate(text):
            if ch in _ZERO_WIDTH:
                repairs.append(f"removed zero-width character U+{ord(ch):04X} at {i}")
                continue
            out.append(ch)
        text = "".join(out)

    if _SARA_AM_RE.search(text):
        for m in _SARA_AM_RE.finditer(text):
            repairs.append(f"recomposed sara am at {m.start()}")
        text = _SARA_AM_RE.sub(lambda m: m.group(1) + _SARA_AM, text)

    return text, repairs


# ---------------------------------------------------------------------------
# Non-Thai field repair (decision 6) — deterministic, no validation
# ---------------------------------------------------------------------------

def repair_non_thai_field(text: str) -> IntegrityResult:
    """Normalise, strip any remaining invalid characters, collapse the
    doubled whitespace that removal leaves behind. No lexicon validation —
    used for english / example_english / romanization_source."""
    original = text or ""
    normalized, repairs = normalise_text(original)

    bad = [(i, ch) for i, ch in enumerate(normalized) if _is_invalid_char(ch)]
    if not bad:
        return IntegrityResult(
            text=normalized, original=original,
            changed=normalized != original, repairs=repairs, invalid_remaining=[],
        )

    bad_indices = {i for i, _ in bad}
    stripped = "".join(ch for i, ch in enumerate(normalized) if i not in bad_indices)
    for i, ch in bad:
        repairs.append(f"removed {_describe(ord(ch))} at {i}")

    collapsed = _WHITESPACE_RUN_RE.sub(" ", stripped).strip()
    if collapsed != stripped:
        repairs.append("collapsed doubled whitespace")

    return IntegrityResult(
        text=collapsed, original=original, changed=True,
        repairs=repairs, invalid_remaining=[],
    )
