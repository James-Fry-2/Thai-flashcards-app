"""LLM fallback for compound-word gloss resolution — resolve_glosses() step 5.

Design constraint: this call NEVER re-segments the word. decompose() has
already picked the parts (minimum-parts DP over the dictionary); this prompt
only fills in glosses that own-cards / the morpheme map / Volubilis / wordnet
all missed, and gives one confidence read on the whole breakdown.

Caller contract: only invoke this when resolve_glosses() left >=1 part with
gloss=None. A fully-glossed breakdown has nothing for this step to add, so
skip the call entirely rather than spend tokens confirming what's already
known.
"""

SYSTEM_PROMPT = """You fill gaps in a Thai compound-word breakdown for a language-learning flashcard app. You get the whole word, its English meaning, and its dictionary segmentation into parts. Some parts already have a gloss; others don't.

For each part WITHOUT a gloss, give its everyday standalone meaning in 1-3 English words, in the sense it carries inside this compound — not an exhaustive list of the word's possible meanings.

Reply with JSON only, no markdown fences, no other text:
{"glosses": {"<part>": "<1-3 word gloss>"}, "confidence": "high"|"medium"|"low"}

"confidence" is about the breakdown as a whole: how transparently do the parts' meanings combine to produce the whole word's meaning? This is independent of how sure you are of any individual gloss.

Only include parts that were missing a gloss in "glosses" — do not repeat parts that already had one. If a part has no sensible standalone meaning in this context (a bound form, a loanword fragment), omit it rather than guessing."""

USER_PROMPT_TEMPLATE = """Word: {thai} ({romanization}) — {english}
Parts: {parts_line}"""


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
    from src.llm.base import LLMMessage

    parts_line = ", ".join(
        f'{p["thai"]} ({p["gloss"]})' if p.get("gloss") else f'{p["thai"]} (?)'
        for p in parts
    )

    return [
        LLMMessage(role="system", content=SYSTEM_PROMPT),
        LLMMessage(
            role="user",
            content=USER_PROMPT_TEMPLATE.format(
                thai=thai,
                romanization=romanization,
                english=english,
                parts_line=parts_line,
            ),
        ),
    ]


def parse_compound_breakdown_response(raw: str, parts: list[dict]) -> tuple[list[dict], str | None]:
    """
    Parse the model's JSON reply and merge filled glosses back into `parts`.

    Returns (updated_parts, confidence). On any parse failure, returns the
    original parts unchanged and confidence=None — callers should treat that
    as "the fallback didn't help," not raise, since this only ever enriches
    an already-valid deterministic breakdown.
    """
    import json
    from json_repair import repair_json

    updated = [dict(p) for p in parts]  # shallow copy, don't mutate caller's list

    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            data = json.loads(repair_json(raw))
        except Exception:
            return updated, None

    if not isinstance(data, dict):
        return updated, None

    glosses = data.get("glosses", {})
    if isinstance(glosses, dict):
        by_thai = {p["thai"]: p for p in updated}
        for part_thai, gloss in glosses.items():
            part = by_thai.get(part_thai)
            if part is not None and part.get("gloss") is None and isinstance(gloss, str) and gloss.strip():
                part["gloss"] = gloss.strip()
                part["gloss_source"] = "llm"

    confidence = data.get("confidence")
    if confidence not in ("high", "medium", "low"):
        confidence = None

    return updated, confidence
