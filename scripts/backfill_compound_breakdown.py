"""
Backfill compound_breakdown and is_compound for all cards.

Targets all cards (is_compound IS NULL) by default, re-resolving any that were
previously skipped (e.g. because the own-cards gloss wasn't available yet).

Usage:
    python scripts/backfill_compound_breakdown.py [--dry-run] [--batch-size N] [--with-llm]

Flags:
    --dry-run      Print what would change without writing to DB.
    --batch-size N Cards per commit (default: 50).
    --with-llm     Enable LLM fallback for this run only (enriches previously-
                   null glosses for words that decompose but lack own-card or
                   wordnet coverage).  Off by default to keep the run cheap.
"""
import argparse
import asyncio
import json
import sys

sys.path.insert(0, "/app")

from loguru import logger
from sqlalchemy import select

from src.db.database import get_session_factory
from src.db.models.card import Card
from src.utils.compound import compute_compound_breakdown, decompose


async def backfill(dry_run: bool, batch_size: int, with_llm: bool) -> None:
    if with_llm:
        logger.info("LLM fallback enabled for this run")

    factory = get_session_factory()

    async with factory() as db:
        result = await db.execute(
            select(Card)
            .where(Card.is_compound.is_(None))
            .where(Card.thai.isnot(None))
            .where(Card.thai != "")
            .order_by(Card.id)
        )
        cards = result.scalars().all()

    logger.info(f"Found {len(cards)} cards with is_compound IS NULL")

    if not cards:
        logger.info("Nothing to do.")
        return

    compounds = 0
    no_breakdown = 0
    updated = 0

    async with factory() as db:
        for i in range(0, len(cards), batch_size):
            batch = cards[i : i + batch_size]
            for card in batch:
                breakdown, is_compound = await compute_compound_breakdown(db, card.thai, syllable_count=card.syllable_count)

                if is_compound:
                    compounds += 1
                else:
                    no_breakdown += 1

                if dry_run:
                    if breakdown:
                        parts_str = " + ".join(
                            f"{p['thai']}({p['gloss'] or '?'})" for p in breakdown
                        )
                        logger.info(f"[dry-run] id={card.id}  {card.thai}  →  {parts_str}")
                    else:
                        logger.debug(f"[dry-run] id={card.id}  {card.thai}  →  not a compound")
                else:
                    db_card = await db.get(Card, card.id)
                    if db_card:
                        db_card.is_compound = is_compound
                        db_card.compound_breakdown = (
                            json.dumps(breakdown, ensure_ascii=False)
                            if breakdown is not None
                            else None
                        )
                        updated += 1

            if not dry_run:
                await db.commit()
                logger.info(
                    f"Committed batch {i // batch_size + 1} "
                    f"({min(i + batch_size, len(cards))}/{len(cards)})"
                )

    if dry_run:
        logger.info(
            f"Dry run complete — {len(cards)} cards: "
            f"{compounds} compounds, {no_breakdown} atomic/loanword"
        )
    else:
        logger.info(
            f"Done — updated {updated} cards: "
            f"{compounds} compounds, {no_breakdown} atomic/loanword"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="Enable LLM fallback for this run (gloss enrichment)",
    )
    args = parser.parse_args()

    asyncio.run(backfill(dry_run=args.dry_run, batch_size=args.batch_size, with_llm=args.with_llm))
