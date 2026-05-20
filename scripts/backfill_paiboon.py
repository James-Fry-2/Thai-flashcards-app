"""
Backfill Paiboon+ romanization for cards that still have RTGS romanization.

Targets cards whose romanization field is all-ASCII (RTGS style, e.g. "sawatdii",
"phom"). Cards that already contain diacritics are assumed to be correct Paiboon+
and are left untouched.

Usage (inside the container or with PYTHONPATH=/app):
    python scripts/backfill_paiboon.py [--dry-run] [--batch-size N]
"""
import argparse
import asyncio
import sys

sys.path.insert(0, "/app")

from loguru import logger
from sqlalchemy import select

from src.db.database import get_session_factory
from src.db.models.card import Card
from src.utils.paiboon import thai_to_paiboon


def _is_rtgs(romanization: str) -> bool:
    """Return True if romanization looks like RTGS (all ASCII, no Paiboon+ diacritics)."""
    return bool(romanization) and all(ord(c) < 128 for c in romanization)


async def backfill(dry_run: bool, batch_size: int) -> None:
    factory = get_session_factory()

    async with factory() as db:
        result = await db.execute(
            select(Card).where(Card.romanization.isnot(None)).order_by(Card.id)
        )
        cards = result.scalars().all()

    rtgs_cards = [c for c in cards if _is_rtgs(c.romanization)]
    logger.info(f"Found {len(rtgs_cards)} cards with RTGS romanization to update "
                f"(of {len(cards)} total with romanization)")

    if not rtgs_cards:
        logger.info("Nothing to do.")
        return

    updated = 0
    skipped = 0

    async with factory() as db:
        for i in range(0, len(rtgs_cards), batch_size):
            batch = rtgs_cards[i : i + batch_size]
            for card in batch:
                new_rom = thai_to_paiboon(card.thai)
                if not new_rom:
                    logger.warning(f"id={card.id} {card.thai!r}: library returned empty, keeping '{card.romanization}'")
                    skipped += 1
                    continue

                if dry_run:
                    logger.info(f"[dry-run] id={card.id}  {card.thai:15s}  '{card.romanization}' → '{new_rom}'")
                else:
                    # Re-fetch card inside the current session to update it
                    db_card = await db.get(Card, card.id)
                    if db_card:
                        db_card.romanization = new_rom
                        updated += 1

            if not dry_run:
                await db.commit()
                logger.info(f"Committed batch {i // batch_size + 1} "
                            f"({min(i + batch_size, len(rtgs_cards))}/{len(rtgs_cards)})")

    if dry_run:
        logger.info(f"Dry run complete — would update {len(rtgs_cards) - skipped} cards, skip {skipped}")
    else:
        logger.info(f"Done — updated {updated}, skipped {skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would change without writing to DB")
    parser.add_argument("--batch-size", type=int, default=50,
                        help="Cards per DB commit (default: 50)")
    args = parser.parse_args()

    asyncio.run(backfill(dry_run=args.dry_run, batch_size=args.batch_size))
