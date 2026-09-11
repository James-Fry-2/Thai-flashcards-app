import json

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.card import Card
from src.llm.prompts.compound_breakdown import (
    build_compound_breakdown_messages,
    parse_compound_breakdown_response,
)
from src.llm.registry import LLMTask, get_provider
from src.utils.compound import decompose, resolve_glosses


async def enrich_breakdown(db: AsyncSession, card_id: int) -> dict:
    """
    Fill in gaps left by resolve_glosses() using an on-demand LLM call.

    Never re-segments the word and never calls the LLM when every part
    already has a gloss — that short-circuit is the cost guard and must run
    before get_provider().

    Available on every compound card, not just ones whose breakdown already
    cleared compound_surface_min_gloss_ratio and got persisted: when
    card.compound_breakdown is still null (the ladder found a gap and the
    default 1.0 ratio held it back from surfacing), this recomputes the same
    canonical segmentation via decompose() — a pure function of `thai`, so
    it's identical to what the automatic pipeline already derived, not a
    re-split — and reruns resolve_glosses() to get the same part list that
    was simply never written to the row.
    """
    card = await db.get(Card, card_id)
    if not card or not card.is_compound:
        return {"status": "not_compound"}

    if card.compound_breakdown:
        try:
            parts = json.loads(card.compound_breakdown)
        except (ValueError, TypeError):
            return {"status": "not_compound"}
        if not isinstance(parts, list) or not parts:
            return {"status": "not_compound"}
    else:
        segments = decompose(card.thai)
        if not segments:
            return {"status": "not_compound"}
        parts = await resolve_glosses(db, segments)

    if all(p.get("gloss") for p in parts):
        return {"status": "no_gaps", "parts": parts}

    messages = build_compound_breakdown_messages(
        thai=card.thai,
        romanization=card.romanization or "",
        english=card.english or "",
        parts=parts,
    )

    provider = get_provider(LLMTask.COMPOUND_BREAKDOWN)
    response = await provider.complete(messages)
    logger.info(
        f"compound_llm_service.enrich_breakdown: card={card_id} "
        f"input_tokens={response.input_tokens} output_tokens={response.output_tokens}"
    )

    updated_parts, confidence = parse_compound_breakdown_response(response.text, parts)

    filled = [
        p["thai"] for p, orig in zip(updated_parts, parts)
        if p.get("gloss") and not orig.get("gloss")
    ]

    # decompose() has known false-positive splits on loanword transliterations
    # and words with meaningless prefixes (see project notes) — words that
    # were never surfaced by the automatic ladder are disproportionately
    # likely to be exactly these bad segmentations, and the model can
    # fabricate plausible-looking glosses for the resulting meaningless
    # fragments (confidence: low is its own signal of this). Only persist
    # when it's reasonably confident in what it filled; a low/unparseable
    # confidence returns the fill for display only, never written to the row.
    persisted = bool(filled) and confidence in ("high", "medium")
    if persisted:
        card.compound_breakdown = json.dumps(updated_parts, ensure_ascii=False)

    return {
        "status": "enriched",
        "parts": updated_parts,
        "confidence": confidence,
        "filled": filled,
        "persisted": persisted,
    }
