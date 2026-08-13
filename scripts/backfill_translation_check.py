"""
Backfill translation_status and translation_candidates for all cards.

Targets cards with translation_status='unverified' by default. Pass --rescan
to re-check every card except those already 'confirmed' — a card the user has
resolved (kept or corrected) is never re-flagged.

Requires the `lexicon` table to be populated (see scripts/ingest_lexicon.py).

Usage:
    python scripts/backfill_translation_check.py [--dry-run] [--batch-size N] [--rescan]

Flags:
    --dry-run      Print what would change without writing to DB.
    --batch-size N Cards per commit (default: 50).
    --rescan       Re-check every card except translation_status='confirmed'.
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
from src.utils.translation_check import check_translation


async def backfill(dry_run: bool, batch_size: int, rescan: bool) -> None:
    if rescan:
        logger.info("Rescan enabled — re-checking all cards except translation_status='confirmed'")

    factory = get_session_factory()

    async with factory() as db:
        query = select(Card).where(Card.thai.isnot(None)).where(Card.thai != "").order_by(Card.id)
        if rescan:
            query = query.where(Card.translation_status != "confirmed")
        else:
            query = query.where(Card.translation_status == "unverified")
        result = await db.execute(query)
        cards = result.scalars().all()

    logger.info(f"Found {len(cards)} cards to process")

    if not cards:
        logger.info("Nothing to do.")
        return

    ok = 0
    flagged = 0
    unverified = 0
    updated = 0

    async with factory() as db:
        for i in range(0, len(cards), batch_size):
            batch = cards[i : i + batch_size]
            for card in batch:
                status, candidates = await check_translation(db, card.thai, card.english)

                if status == "ok":
                    ok += 1
                elif status == "flagged":
                    flagged += 1
                else:
                    unverified += 1

                if dry_run:
                    if status == "flagged":
                        logger.info(
                            f"[dry-run] id={card.id}  {card.thai} → {card.english!r}  "
                            f"flagged: dictionary suggests {candidates}"
                        )
                    else:
                        logger.debug(f"[dry-run] id={card.id}  {card.thai}  → {status}")
                else:
                    db_card = await db.get(Card, card.id)
                    if db_card:
                        db_card.translation_status = status
                        db_card.translation_candidates = (
                            json.dumps(candidates, ensure_ascii=False) if candidates else None
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
            f"{ok} ok, {flagged} flagged, {unverified} unverified"
        )
    else:
        logger.info(
            f"Done — updated {updated} cards: "
            f"{ok} ok, {flagged} flagged, {unverified} unverified"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument(
        "--rescan",
        action="store_true",
        help="Re-check all cards except translation_status='confirmed'",
    )
    args = parser.parse_args()

    asyncio.run(backfill(dry_run=args.dry_run, batch_size=args.batch_size, rescan=args.rescan))
