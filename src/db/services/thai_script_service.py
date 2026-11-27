"""Turn romanized (or English) text that ended up in a card's Thai field
into Thai script.

Some textbook pages print example sentences only in English and
romanization. Card generation then copied the romanization into ``thai``,
which breaks romanization, analysis and speech for that card. This module
detects that case and asks Claude to write the Thai script.

has_thai_script(text)                 -> bool
looks_romanized(text)                 -> bool   (tone-marked Latin, ɔ/ɛ/ə/ʉ/ŋ, ˑ joins)
await to_thai_script(items)           -> list[Conversion | None]
    items: [{"text", "english", "hint"}]; hint is any Thai already on the
    card (e.g. its example sentence), which is often the same phrase.
    None for an item the model couldn't convert or whose output failed
    validation.
agreement(source_romanization, thai)  -> float 0..1, how closely our own
    romanization of the result matches the source; a review aid only.
"""
from __future__ import annotations

import difflib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from src.llm.base import LLMMessage
from src.llm.registry import LLMTask, get_provider
from src.utils.text_integrity import find_invalid_chars, normalise_text

_THAI_RE = re.compile("[ก-๛]")
_LATIN_RE = re.compile("[A-Za-z]")
_ROMANIZATION_MARKS = set("ɔɛəʉŋɯˑ·")

SYSTEM = """You convert romanized Thai back into standard Thai script for a learner's flashcards.

The romanization comes from a Thai textbook. It marks tones with accents on vowels (à á â ǎ), uses ɔ ɛ ə ʉ ŋ for Thai vowels and ng, and joins the syllables of one word with ˑ or ·. Write exactly what was said, in correct, natural Thai spelling. Use the English meaning to choose between words that sound alike.

- Keep alternatives the book gives with a slash, e.g. "phǒm/chǎn" -> "ผม/ฉัน", "khráp/khâ" -> "ครับ/ค่ะ".
- Keep optional words in parentheses, e.g. "mʉ̂aˑwaan (níi)" -> "เมื่อวาน (นี้)".
- Write the Thai without spaces between words, as Thai is written; only keep a space where the romanization separates two sentences or clauses.
- Keep the source's question or ending punctuation only if Thai would use it.
- If the text is English, or an English loanword with no romanization (e.g. "Jazz"), give the Thai the learner should study: the usual Thai spelling of the loanword, or the natural Thai for the English phrase.
- A "hint" is Thai already on the same card. It is often this exact phrase; use it when it matches the romanization, but don't copy it if it says something different.

Set "source" to "romanization" if the input was romanized Thai, "english" if it was English. Set confidence to "low" when you are unsure of a spelling or a word, with a one-sentence note on what is uncertain; otherwise "high" and an empty note."""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "thai": {"type": "string"},
                    "source": {"type": "string", "enum": ["romanization", "english"]},
                    "confidence": {"type": "string", "enum": ["high", "low"]},
                    "note": {"type": "string"},
                },
                "required": ["index", "thai", "source", "confidence", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


@dataclass
class Conversion:
    thai: str
    source: str        # "romanization" | "english"
    confidence: str    # "high" | "low"
    note: str
    model: str


def has_thai_script(text: Optional[str]) -> bool:
    return bool(text) and bool(_THAI_RE.search(text))


def looks_romanized(text: Optional[str]) -> bool:
    """Tone-marked or IPA-style Latin, as textbooks print romanized Thai."""
    if not text or has_thai_script(text):
        return False
    if any(ch in _ROMANIZATION_MARKS for ch in text):
        return True
    decomposed = unicodedata.normalize("NFD", text)
    return any(unicodedata.combining(ch) for ch in decomposed)


def _valid(thai: str) -> Optional[str]:
    thai, _ = normalise_text(thai or "")
    thai = " ".join(thai.split())
    if not has_thai_script(thai) or _LATIN_RE.search(thai) or find_invalid_chars(thai):
        return None
    return thai


async def to_thai_script(items: list[dict]) -> list[Optional[Conversion]]:
    if not items:
        return []
    payload = [
        {"index": i, "text": it["text"], "english": it.get("english") or "", "hint": it.get("hint") or ""}
        for i, it in enumerate(items)
    ]
    provider = get_provider(LLMTask.THAI_SCRIPT)
    response = await provider.complete(
        [
            LLMMessage(role="system", content=SYSTEM),
            LLMMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
        ],
        json_schema=SCHEMA,
    )
    data = json.loads(response.text)
    out: list[Optional[Conversion]] = [None] * len(items)
    for row in data.get("items", []):
        i = row.get("index")
        if not isinstance(i, int) or not 0 <= i < len(items):
            continue
        thai = _valid(row.get("thai", ""))
        if thai is None:
            continue
        out[i] = Conversion(
            thai=thai,
            source=row.get("source", "romanization"),
            confidence=row.get("confidence", "low"),
            note=(row.get("note") or "").strip(),
            model=response.model,
        )
    return out


_FOLD = str.maketrans({"ɔ": "o", "ɛ": "e", "ə": "e", "ʉ": "u", "ɯ": "u", "ŋ": "ng"})


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower()).translate(_FOLD)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z]", "", text)


def agreement(source_romanization: str, thai: str) -> float:
    """How closely our own Paiboon romanization of *thai* matches the book's
    romanization, ignoring tone marks and spacing. Rough: 1.0 is a match,
    below ~0.7 is worth a look."""
    from src.utils.romanization import generate_all

    ours = generate_all(thai).get("paiboon") or ""
    a, b = _fold(source_romanization), _fold(ours)
    if not a or not b:
        return 0.0
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 2)
