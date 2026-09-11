import json

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.card import Card
from src.llm.prompts.translation_verify import (
    build_translation_verify_messages,
    parse_translation_verify_response,
)
from src.llm.registry import LLMTask, get_provider


async def verify_translation(db: AsyncSession, card_id: int) -> dict:
    """
    Ask the LLM whether a lexicon-flagged translation is a real catch.

    Advisory only: does not touch translation_status, english, or any
    override. Never calls the LLM unless the card is currently flagged.
    """
    card = await db.get(Card, card_id)
    if not card or card.translation_status != "flagged":
        return {"status": "not_flagged"}

    candidates: list[str] = []
    if card.translation_candidates:
        try:
            parsed = json.loads(card.translation_candidates)
            if isinstance(parsed, list):
                candidates = [c for c in parsed if isinstance(c, str)]
        except (ValueError, TypeError):
            candidates = []

    messages = build_translation_verify_messages(
        thai=card.thai,
        romanization=card.romanization or "",
        english=card.english or "",
        candidates=candidates,
    )

    provider = get_provider(LLMTask.TRANSLATION_VERIFY)
    response = await provider.complete(messages)
    logger.info(
        f"translation_verify_service.verify_translation: card={card_id} "
        f"input_tokens={response.input_tokens} output_tokens={response.output_tokens}"
    )

    verdict, reason = parse_translation_verify_response(response.text)

    return {"status": "checked", "verdict": verdict, "reason": reason}
