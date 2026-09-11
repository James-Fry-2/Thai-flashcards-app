"""LLM second opinion on a lexicon-flagged translation.

translation_check.py flags a card when the material English shares zero
content-token overlap with any Volubilis translation. That catch is purely
lexical, so it over-flags legitimate paraphrases, less-common senses, and
register differences.

Same budget principle as compound_breakdown.py: this call does not go
looking for translations. It takes the candidates translation_check.py
already fetched and judges the flag itself, nothing more.
"""

SYSTEM_PROMPT = """You give a second opinion on a possible Thai-to-English mistranslation. Lexicon lookup flagged it because the learner's material translation shares no words with the dictionary's suggestions — but that check is purely mechanical, so it also flags legitimate paraphrases and less common senses that just don't share vocabulary with the dictionary entry.

These cards are for receptive review: the learner sees the Thai and recalls the English. Judge whether the material translation teaches the right mapping, not whether it would produce the right effect in conversation.

Reply with JSON only, no markdown fences, no other text:
{"verdict": "likely_error"|"likely_ok"|"unsure", "reason": "<one short sentence>"}

- likely_error: the material translation would teach the learner something wrong. This includes plain wrong words, mismatched senses, and a translation that conveys the right pragmatic effect in one situation without being an actual sense of the Thai.
- likely_ok: the material translation is a valid sense or a fair paraphrase of what the Thai means, even if it shares no vocabulary with the dictionary entry, and even if it captures only one of several senses. Covering one real sense but not others is not an error.
- unsure: genuinely ambiguous without more context.

You are judging whether the flag is correct, not choosing or generating a translation."""

USER_PROMPT_TEMPLATE = """Word: {thai} ({romanization})
Material translation: {english}
Dictionary suggests: {candidates_line}"""


def build_translation_verify_messages(
    thai: str,
    romanization: str,
    english: str,
    candidates: list[str],
) -> list:
    """
    candidates: translation_check.py's already-fetched Volubilis translations
    (card.translation_candidates, capped at 5). Not re-queried here.
    """
    from src.llm.base import LLMMessage

    candidates_line = ", ".join(candidates) if candidates else "(none on file)"

    return [
        LLMMessage(role="system", content=SYSTEM_PROMPT),
        LLMMessage(
            role="user",
            content=USER_PROMPT_TEMPLATE.format(
                thai=thai,
                romanization=romanization,
                english=english,
                candidates_line=candidates_line,
            ),
        ),
    ]


def parse_translation_verify_response(raw: str) -> tuple[str | None, str | None]:
    """
    Returns (verdict, reason). On any parse failure, returns (None, None) —
    callers should treat that as "no second opinion available" and leave the
    existing flag exactly as translation_check.py set it.
    """
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
            return None, None

    if not isinstance(data, dict):
        return None, None

    verdict = data.get("verdict")
    if verdict not in ("likely_error", "likely_ok", "unsure"):
        verdict = None

    reason = data.get("reason")
    reason = reason.strip() if isinstance(reason, str) and reason.strip() else None

    return verdict, reason
