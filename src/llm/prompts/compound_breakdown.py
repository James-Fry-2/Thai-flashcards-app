"""LLM fallback for compound-word gloss resolution — resolve_glosses() step 5.

Design constraint: neither call here ever re-segments the word. decompose()
has already picked the parts (minimum-parts DP over the dictionary); these
prompts only touch glosses.

Two independent modes, two callers:
- fill (build_compound_breakdown_messages / parse_compound_breakdown_response):
  only fills glosses the deterministic ladder missed. Caller contract: only
  invoke when resolve_glosses() left >=1 part with gloss=None.
- review (build_compound_breakdown_review_messages /
  parse_compound_breakdown_review_response): fills gaps AND asks the model to
  flag existing glosses that don't fit this compound. Advisory only — see
  compound_llm_service.review_breakdown for why corrections are never
  auto-persisted.
"""

FILL_SYSTEM_PROMPT = """You fill gaps in a Thai compound-word breakdown for a language-learning flashcard app. You get the whole word, its English meaning, and its dictionary segmentation into parts. Some parts already have a gloss; others don't.

For each part WITHOUT a gloss, give its everyday standalone meaning in 1-3 English words, in the sense it carries inside this compound — not an exhaustive list of the word's possible meanings.

Reply with JSON only, no markdown fences, no other text:
{"glosses": {"<part>": "<1-3 word gloss>"}, "confidence": "high"|"medium"|"low"}

"confidence" is about the breakdown as a whole: how transparently do the parts' meanings combine to produce the whole word's meaning? This is independent of how sure you are of any individual gloss.

Only include parts that were missing a gloss in "glosses" — do not repeat parts that already had one. If a part has no sensible standalone meaning in this context (a bound form, a loanword fragment), omit it rather than guessing."""

REVIEW_SYSTEM_PROMPT = """You review a Thai compound-word breakdown for a language-learning flashcard app. You get the whole word, its English meaning, and its dictionary segmentation into parts, each shown with its current gloss (or "?" if it has none).

For each part WITHOUT a gloss, give its everyday standalone meaning in 1-3 English words, in the sense it carries inside this compound.

For each part that ALREADY has a gloss, check whether that gloss is the right sense for THIS compound. Most existing glosses are correct — only flag one if it is clearly wrong or misleading in context (a rare/technical sense, an unrelated word, or a sense that doesn't fit the compound's meaning at all). Do not flag a gloss just because you'd phrase it slightly differently.

Reply with JSON only, no markdown fences, no other text:
{"glosses": {"<part>": "<1-3 word gloss>"}, "corrections": {"<part>": {"suggested": "<1-3 word gloss>", "reason": "<reason, under 12 words>"}}, "confidence": "high"|"medium"|"low"}

"confidence" is about the breakdown as a whole: how transparently do the parts' meanings combine to produce the whole word's meaning.

Only include parts that were missing a gloss in "glosses". Only include parts whose existing gloss you are flagging as wrong in "corrections" — omit every part whose existing gloss is fine. If a gap has no sensible standalone meaning in this context (a bound form, a loanword fragment), omit it from "glosses" rather than guessing."""

USER_PROMPT_TEMPLATE = """Word: {thai} ({romanization}) — {english}
Parts: {parts_line}"""


def _parts_line(parts: list[dict]) -> str:
    return ", ".join(
        f'{p["thai"]} ({p["gloss"]})' if p.get("gloss") else f'{p["thai"]} (?)'
        for p in parts
    )


def _build_messages(system_prompt: str, thai: str, romanization: str, english: str, parts: list[dict]) -> list:
    from src.llm.base import LLMMessage

    return [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(
            role="user",
            content=USER_PROMPT_TEMPLATE.format(
                thai=thai,
                romanization=romanization,
                english=english,
                parts_line=_parts_line(parts),
            ),
        ),
    ]


def build_compound_breakdown_messages(
    thai: str,
    romanization: str,
    english: str,
    parts: list[dict],
) -> list:
    """
    parts: the per-part dicts already produced by resolve_glosses(), e.g.
        [{"thai": "เสื้อ", "gloss": "shirt", "gloss_source": "lexicon"},
         {"thai": "คลุม", "gloss": None, "gloss_source": None}]

    The segmentation is used exactly as given — this function does not call
    decompose() or otherwise alter the part list.
    """
    return _build_messages(FILL_SYSTEM_PROMPT, thai, romanization, english, parts)


def build_compound_breakdown_review_messages(
    thai: str,
    romanization: str,
    english: str,
    parts: list[dict],
) -> list:
    """Same input contract as build_compound_breakdown_messages, but the
    model is also asked to flag existing glosses that look wrong."""
    return _build_messages(REVIEW_SYSTEM_PROMPT, thai, romanization, english, parts)


def _parse_json_reply(raw: str) -> dict | None:
    import json
    from json_repair import repair_json

    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            data = json.loads(repair_json(raw))
        except Exception:
            return None

    return data if isinstance(data, dict) else None


def _merge_glosses(data: dict, parts: list[dict]) -> list[dict]:
    updated = [dict(p) for p in parts]  # shallow copy, don't mutate caller's list

    glosses = data.get("glosses", {})
    if isinstance(glosses, dict):
        by_thai = {p["thai"]: p for p in updated}
        for part_thai, gloss in glosses.items():
            part = by_thai.get(part_thai)
            if part is not None and part.get("gloss") is None and isinstance(gloss, str) and gloss.strip():
                part["gloss"] = gloss.strip()
                part["gloss_source"] = "llm"

    return updated


def _confidence(data: dict) -> str | None:
    confidence = data.get("confidence")
    return confidence if confidence in ("high", "medium", "low") else None


def parse_compound_breakdown_response(raw: str, parts: list[dict]) -> tuple[list[dict], str | None]:
    """
    Parse the model's JSON reply and merge filled glosses back into `parts`.

    Returns (updated_parts, confidence). On any parse failure, returns the
    original parts unchanged and confidence=None — callers should treat that
    as "the fallback didn't help," not raise, since this only ever enriches
    an already-valid deterministic breakdown.
    """
    data = _parse_json_reply(raw)
    if data is None:
        return [dict(p) for p in parts], None

    return _merge_glosses(data, parts), _confidence(data)


def parse_compound_breakdown_review_response(
    raw: str, parts: list[dict]
) -> tuple[list[dict], list[dict], str | None]:
    """
    Parse a review reply into (updated_parts, corrections, confidence).

    updated_parts: `parts` with gaps filled exactly like
    parse_compound_breakdown_response — never touches a part that already
    had a gloss.

    corrections: one entry per part the model flagged, each
    {"thai", "current_gloss", "suggested_gloss", "reason"} — only for parts
    that had a non-null gloss in the input and a distinct, non-empty
    suggested replacement. Advisory: not merged into updated_parts, since
    unlike a gap-fill this overwrites an existing (possibly already-correct)
    value and the caller must not persist it without user confirmation.

    On any parse failure, returns (parts unchanged, [], None).
    """
    data = _parse_json_reply(raw)
    if data is None:
        return [dict(p) for p in parts], [], None

    updated = _merge_glosses(data, parts)

    corrections: list[dict] = []
    raw_corrections = data.get("corrections", {})
    if isinstance(raw_corrections, dict):
        by_thai = {p["thai"]: p for p in parts}
        for part_thai, entry in raw_corrections.items():
            part = by_thai.get(part_thai)
            if part is None or not part.get("gloss") or not isinstance(entry, dict):
                continue
            suggested = entry.get("suggested")
            if not isinstance(suggested, str) or not suggested.strip():
                continue
            suggested = suggested.strip()
            if suggested == part["gloss"]:
                continue
            reason = entry.get("reason")
            corrections.append(
                {
                    "thai": part_thai,
                    "current_gloss": part["gloss"],
                    "suggested_gloss": suggested,
                    "reason": reason.strip() if isinstance(reason, str) and reason.strip() else None,
                }
            )

    return updated, corrections, _confidence(data)
