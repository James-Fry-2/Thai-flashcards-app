SYSTEM_PROMPT = """You are a Thai flashcard tagger for a personal Thai vocabulary app. Given a batch of flashcards, assign each card a topic and a small set of descriptive tags.

Output ONLY a valid JSON array — no markdown code fences, no explanations, no extra text."""

USER_PROMPT_TEMPLATE = """Tag each card below. Output a JSON array with one object per card.

Output schema per card:
{{
  "id": <card id as integer>,
  "topic": "<short topic name, 1-3 words, title-case, e.g. 'Food', 'Family', 'Question Particles'>",
  "tags": ["<0-4 lowercase tag strings>"]
}}

Rules:
- PREFER an existing topic name if one fits reasonably well. Only propose a new topic name if nothing in the existing list is close.
- Topic names must be short, title-case, broad categories — not overly specific. Good: "Food", "Travel", "Body Parts". Bad: "Thai Street Food Vendors", "Medical Symptoms Detail".
- For function words, particles, or grammar patterns, use topic "Grammar" or "Particles" rather than a semantic field.
- Tags are lowercase, single words or short hyphenated phrases. Useful categories:
  - Part of speech: noun, verb, adjective, adverb, particle, classifier, conjunction, preposition
  - Formality: formal, informal, polite, slang, colloquial
  - Register: spoken, written, royal
  - Card hints: idiom, collocation, loanword, honorific
- Aim for 2-4 tags per card. Fewer is fine for simple words. Do not tag every possible attribute.
- Return exactly one object per card id supplied. Do not skip any card.

Existing topics (prefer these):
{existing_topics}

Cards to tag:
{cards}"""


def build_card_tagging_messages(cards: list[dict], existing_topics: list[str]) -> list:
    from src.llm.base import LLMMessage

    topics_str = ", ".join(existing_topics) if existing_topics else "(none yet — create appropriate topic names)"

    card_lines = []
    for c in cards:
        line = f'  id:{c["id"]} thai:"{c["thai"]}" english:"{c["english"]}"'
        if c.get("example_thai"):
            line += f' example:"{c["example_thai"]}"'
        card_lines.append(line)

    return [
        LLMMessage(role="system", content=SYSTEM_PROMPT),
        LLMMessage(
            role="user",
            content=USER_PROMPT_TEMPLATE.format(
                existing_topics=topics_str,
                cards="\n".join(card_lines),
            ),
        ),
    ]
