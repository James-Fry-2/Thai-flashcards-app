SYSTEM_PROMPT = """You are a Thai language flashcard assistant. Given a target flashcard and a list of candidate cards, identify which candidates are meaningfully related to the target and classify the relationship type.

Output ONLY a valid JSON array — no markdown code fences, no explanations, no extra text.
If no candidates are related, return an empty array: []"""

USER_PROMPT_TEMPLATE = """Target card:
  thai: {thai}
  english: {english}
  type: {card_type}
  tags: {tags}

Candidate cards:
{candidates}

For each candidate that is meaningfully related to the target, return a JSON object:
{{
  "card_id": <integer id of the candidate>,
  "link_type": "<one of: related | prerequisite | antonym | same_root | variant>",
  "confidence": <float 0.0-1.0>,
  "reason": "<one sentence explaining the relationship>"
}}

Link type definitions:
- related: thematically connected (same topic, co-occurs in speech)
- prerequisite: the candidate should be learned BEFORE the target
- antonym: opposite meaning
- same_root: shares the same Thai root word or morpheme
- variant: alternative spelling, register, or formality level of the same concept

Rules:
- Only include candidates with confidence >= 0.6
- Do not include the target card itself
- A card can only appear once in the output"""


def build_link_suggestion_messages(
    thai: str,
    english: str,
    card_type: str,
    tags: list[str],
    candidates: list[dict],
) -> list:
    from src.llm.base import LLMMessage

    candidate_lines = "\n".join(
        f'  - id:{c["id"]} thai:"{c["thai"]}" english:"{c["english"]}" type:{c["card_type"]}'
        for c in candidates
    )
    tags_str = ", ".join(tags) if tags else "none"

    return [
        LLMMessage(role="system", content=SYSTEM_PROMPT),
        LLMMessage(
            role="user",
            content=USER_PROMPT_TEMPLATE.format(
                thai=thai,
                english=english,
                card_type=card_type,
                tags=tags_str,
                candidates=candidate_lines,
            ),
        ),
    ]
