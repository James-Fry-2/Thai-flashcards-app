import json

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.card import Card
from src.llm.prompts.compound_breakdown import (
    build_compound_breakdown_messages,
    build_compound_breakdown_review_messages,
    parse_compound_breakdown_response,
    parse_compound_breakdown_review_response,
)
from src.llm.registry import LLMTask, get_provider
from src.utils.card_overrides import upsert_flag
from src.utils.compound import decompose, resolve_glosses
from src.utils.current_user import current_user


async def _current_parts(db: AsyncSession, card: Card) -> list[dict] | None:
    """The same canonical part list the automatic pipeline derived for this
    card — from the persisted breakdown if one surfaced, otherwise
    recomputed via decompose()/resolve_glosses() (pure functions of `thai`,
    so identical to what the ladder already found, not a re-split).

    Returns None when the card isn't a usable compound (not flagged
    is_compound, or decompose() finds nothing to work with).
    """
    if not card.is_compound:
        return None

    if card.compound_breakdown:
        try:
            parts = json.loads(card.compound_breakdown)
        except (ValueError, TypeError):
            return None
        if not isinstance(parts, list) or not parts:
            return None
        return parts

    segments = decompose(card.thai)
    if not segments:
        return None
    return await resolve_glosses(db, segments)


async def enrich_breakdown(db: AsyncSession, card_id: int) -> dict:
    """
    Fill in gaps left by resolve_glosses() using an on-demand LLM call.

    Never re-segments the word and never calls the LLM when every part
    already has a gloss — that short-circuit is the cost guard and must run
    before get_provider().
    """
    card = await db.get(Card, card_id)
    parts = await _current_parts(db, card) if card else None
    if parts is None:
        return {"status": "not_compound"}

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
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
    }


async def review_breakdown(db: AsyncSession, card_id: int) -> dict:
    """
    Ask the LLM to fill gaps AND flag existing glosses that look wrong for
    this compound, using a single on-demand call.

    Unlike enrich_breakdown, this always calls the LLM — even when every
    part already has a gloss — since checking existing glosses is the whole
    point. The gloss value itself is purely advisory: never writes to
    card.compound_breakdown. The deterministic ladder (own cards > morpheme
    map > Volubilis > wordnet) is trustworthy enough that overwriting one of
    its glosses without a human looking at it first is a worse failure mode
    than a stale gloss; the caller applies any suggestion the user accepts
    via the existing compound override endpoint.

    When it finds >=1 correction at confidence high/medium (same bar
    enrich_breakdown uses to decide a fill is worth persisting), it opens an
    (idempotent) CardFlag(target='compound') so the card surfaces under the
    /cards needs_attention filter even after the caller navigates away —
    otherwise a review result that isn't acted on immediately just evaporates
    with the React Query cache. Low-confidence corrections don't flag: they're
    exactly the noisy guesses that shouldn't build up a worklist.
    """
    card = await db.get(Card, card_id)
    parts = await _current_parts(db, card) if card else None
    if parts is None:
        return {"status": "not_compound"}

    messages = build_compound_breakdown_review_messages(
        thai=card.thai,
        romanization=card.romanization or "",
        english=card.english or "",
        parts=parts,
    )

    provider = get_provider(LLMTask.COMPOUND_BREAKDOWN)
    response = await provider.complete(messages)
    logger.info(
        f"compound_llm_service.review_breakdown: card={card_id} "
        f"input_tokens={response.input_tokens} output_tokens={response.output_tokens}"
    )

    updated_parts, corrections, confidence = parse_compound_breakdown_review_response(
        response.text, parts
    )

    filled = [
        p["thai"] for p, orig in zip(updated_parts, parts)
        if p.get("gloss") and not orig.get("gloss")
    ]

    flagged = False
    if corrections and confidence in ("high", "medium"):
        note = f"AI review found {len(corrections)} possible gloss correction(s): " + ", ".join(
            f'{c["thai"]} → "{c["suggested_gloss"]}"' for c in corrections
        )
        flagged_value = json.dumps(
            {"corrections": corrections, "confidence": confidence}, ensure_ascii=False
        )
        await upsert_flag(db, current_user(), card_id, "compound", note, flagged_value)
        flagged = True

    return {
        "status": "reviewed",
        "parts": updated_parts,
        "confidence": confidence,
        "filled": filled,
        "corrections": corrections,
        "flagged": flagged,
    }
