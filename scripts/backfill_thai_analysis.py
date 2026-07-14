"""
Backfill Thai script analysis for cards that have not yet been analysed.

Targets cards where syllable_count IS NULL (i.e. created before the analysis
pipeline was wired in, or where analysis failed at creation time).

Usage (inside the container or with PYTHONPATH=/app):
    python scripts/backfill_thai_analysis.py [--dry-run] [--batch-size N]
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
from src.utils.thai_analysis import analyze_thai, _EMPTY_RESULT


def _is_empty(analysis: dict) -> bool:
    """Return True if analyze_thai returned the empty-default result."""
    return analysis["syllable_count"] == 0 and analysis["tone_pattern"] == []


async def backfill(dry_run: bool, batch_size: int) -> None:
    factory = get_session_factory()

    async with factory() as db:
        result = await db.execute(
            select(Card)
            .where(Card.syllable_count.is_(None))
            .where(Card.thai.isnot(None))
            .where(Card.thai != "")
            .order_by(Card.id)
        )
        cards = result.scalars().all()

    logger.info(f"Found {len(cards)} cards needing Thai analysis")

    if not cards:
        logger.info("Nothing to do.")
        return

    failed = 0
    updated = 0

    async with factory() as db:
        for i in range(0, len(cards), batch_size):
            batch = cards[i : i + batch_size]
            for card in batch:
                analysis = analyze_thai(card.thai)

                if _is_empty(analysis):
                    logger.warning(
                        f"id={card.id} {card.thai!r}: analysis returned empty defaults"
                    )
                    failed += 1

                if dry_run:
                    logger.info(
                        f"[dry-run] id={card.id}  {card.thai:20s}  "
                        f"syllables={analysis['syllable_count']}  "
                        f"tones={analysis['tone_pattern']}  "
                        f"cluster={analysis['has_cluster']}"
                    )
                else:
                    db_card = await db.get(Card, card.id)
                    if db_card:
                        db_card.syllable_count = analysis["syllable_count"]
                        db_card.tone_pattern = json.dumps(
                            analysis["tone_pattern"], ensure_ascii=False
                        )
                        db_card.consonant_classes = json.dumps(
                            analysis["consonant_classes"], ensure_ascii=False
                        )
                        db_card.has_cluster = analysis["has_cluster"]
                        db_card.has_rare_consonant = analysis["has_rare_consonant"]
                        db_card.has_silent_mark = analysis["has_silent_mark"]
                        db_card.script_analysis = json.dumps(
                            analysis["script_analysis"], ensure_ascii=False
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
            f"Dry run complete — would process {len(cards)} cards "
            f"({failed} returned empty defaults)"
        )
    else:
        logger.info(f"Done — updated {updated}, failed analysis {failed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without writing to DB",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Cards per DB commit (default: 50)",
    )
    args = parser.parse_args()

    asyncio.run(backfill(dry_run=args.dry_run, batch_size=args.batch_size))
