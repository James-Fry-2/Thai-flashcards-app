"""
Pure normalisation helpers for the correction-event log
(card_correction_event). No DB access here — see
src/db/services/correction_service.py for the write/read path.
"""
from __future__ import annotations

import unicodedata

_ZERO_WIDTH = ("​", "‌", "‍", "﻿")
_TRAILING_PUNCT = ".!?"
_QUOTES = "\"'‘’“”"


def thai_key(s: str) -> str:
    """Normalised comparison key for a card's Thai text: NFC, stripped, with
    zero-width characters removed and internal whitespace collapsed.

    Raises ValueError on U+FFFD (the Unicode replacement character) so a
    corrupted import can never silently become a match key that other,
    genuinely-clean cards get matched against.
    """
    if "�" in s:
        raise ValueError("thai_key: input contains U+FFFD (replacement character)")

    normalized = unicodedata.normalize("NFC", s).strip()
    for ch in _ZERO_WIDTH:
        normalized = normalized.replace(ch, "")
    return " ".join(normalized.split())


def english_norm(s: str) -> str:
    """Normalised comparison key for an English value: NFC, casefolded,
    whitespace-collapsed, with surrounding quotes and trailing ./!/? stripped.

    Deliberately does not stem or strip articles — "the bill" and "bill"
    must stay distinct comparison keys.
    """
    normalized = unicodedata.normalize("NFC", s).casefold().strip()
    normalized = " ".join(normalized.split())
    normalized = normalized.strip(_QUOTES)
    while normalized and normalized[-1] in _TRAILING_PUNCT:
        normalized = normalized[:-1].rstrip()
    return normalized


def from_norm(target: str, from_value: dict | None) -> str | None:
    """The normalised comparison key derived from an event's from_value,
    used to find other cards showing the same (wrong) value. Returns None
    for targets with no defined comparison (romanization, other)."""
    if not from_value:
        return None

    if target == "translation":
        english = from_value.get("english")
        if not isinstance(english, str):
            return None
        return english_norm(english)

    if target == "compound":
        parts = from_value.get("parts")
        if not isinstance(parts, list):
            return None
        return "|".join(
            f"{p.get('thai', '')}={english_norm(p.get('gloss') or '')}"
            for p in parts
            if isinstance(p, dict)
        )

    return None
