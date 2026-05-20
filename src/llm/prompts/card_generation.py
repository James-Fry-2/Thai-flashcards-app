SYSTEM_PROMPT = """You are a Thai language flashcard generator. Your job is to extract vocabulary, phrases, and grammar patterns from Thai learning notes and output structured flashcard data.

Output ONLY a valid JSON array — no markdown code fences, no explanations, no extra text. If no Thai content is found, return an empty array: []"""

USER_PROMPT_TEMPLATE = """Extract all Thai vocabulary, phrases, and grammar patterns from the text below.

For each item produce a JSON object matching this exact schema:
{{
  "thai": "กิน",
  "romanization": "gin1",
  "english": "to eat",
  "example_thai": "ฉันกินข้าวทุกวัน",
  "example_english": "I eat rice every day",
  "card_type": "vocab"
}}

Rules:
- "thai": the exact Thai word, phrase, or grammar pattern
- "romanization": If Paiboon+ romanization for this word or phrase is explicitly written in the
  source text (e.g. "กิน gin1", "สวัสดี sà-wàt-dii", or similar Latin-script pronunciation guide
  alongside the Thai), copy it exactly. If no romanization appears in the source text, return null.
  Do NOT invent romanization — null means "not found in source material".
- "english": concise translation, 8 words or fewer
- "example_thai": a natural, complete Thai sentence using the item
- "example_english": English translation of the example sentence
- "card_type": one of "vocab" (single word), "phrase" (multi-word expression), or "grammar" (pattern/structure)
- Do not include duplicates
- For grammar patterns, use the pattern notation as "thai" (e.g. "ถ้า...ก็...")

TEXT:
{raw_text}"""


def build_card_generation_messages(raw_text: str) -> list:
    from src.llm.base import LLMMessage
    return [
        LLMMessage(role="system", content=SYSTEM_PROMPT),
        LLMMessage(role="user", content=USER_PROMPT_TEMPLATE.format(raw_text=raw_text)),
    ]
