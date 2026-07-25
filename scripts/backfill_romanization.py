"""
Backfill romanization scheme columns for cards that predate the i9j0k1l2m3n4 migration.

For every card with Thai script:
  - Computes romanization_paiboon / rtgs / ipa via generate_all.
  - Leaves romanization_source and romanization_manual null (existing cards have no
    separable source record; their effective romanization stays generated Paiboon+
    under the default preference, matching today's post-backfill state).
  - Recomputes effective romanization via resolve_effective under current preferences.

Usage (inside the container or with PYTHONPATH=/app):
    python scripts/backfill_romanization.py [--dry-run] [--batch-size N]
"""
import argparse
import asyncio
import sys

sys.path.insert(0, "/app")

from loguru import logger
from sqlalchemy import select

from src.db.database import get_session_factory
from src.db.models.card import Card
from src.db.services.preferences_service import get_preferences
from src.utils.romanization import generate_all, resolve_effective


async def backfill(dry_run: bool, batch_size: int) -> None:
    factory = get_session_factory()

    async with factory() as db:
        prefs = await get_preferences(db)
        await db.commit()
        display = prefs.romanization_display
        fallback = prefs.romanization_fallback

    logger.info(
        f"Preferences: romanization_display={display!r}, romanization_fallback={fallback!r}"
    )

    async with factory() as db:
        result = await db.execute(
            select(Card).where(Card.thai.isnot(None)).order_by(Card.id)
        )
        cards = result.scalars().all()

    logger.info(f"Found {len(cards)} cards with Thai script to process")

    if not cards:
        logger.info("Nothing to do.")
        return

    updated = 0
    skipped = 0

    async with factory() as db:
        prefs = await get_preferences(db)

        for i in range(0, len(cards), batch_size):
            batch = cards[i: i + batch_size]
            for card in batch:
                schemes = await asyncio.to_thread(generate_all, card.thai)

                paiboon = schemes.get("paiboon") or None
                rtgs = schemes.get("rtgs") or None
                ipa = schemes.get("ipa") or None

                values = {
                    "romanization_source": card.romanization_source,
                    "romanization_paiboon": paiboon,
                    "romanization_rtgs": rtgs,
                    "romanization_ipa": ipa,
                    "romanization_manual": card.romanization_manual,
                }
                effective = resolve_effective(values, prefs)

                if dry_run:
                    logger.info(
                        f"[dry-run] id={card.id}  {card.thai!r}  "
                        f"paiboon={paiboon!r}  rtgs={rtgs!r}  "
                        f"ipa={ipa!r}  effective={effective!r}"
                    )
                    updated += 1
                    continue

                db_card = await db.get(Card, card.id)
                if db_card:
                    db_card.romanization_paiboon = paiboon
                    db_card.romanization_rtgs = rtgs
                    db_card.romanization_ipa = ipa
                    db_card.romanization = effective
                    updated += 1
                else:
                    skipped += 1

            if not dry_run:
                await db.commit()
                logger.info(
                    f"Committed batch {i // batch_size + 1} "
                    f"({min(i + batch_size, len(cards))}/{len(cards)})"
                )

    if dry_run:
        logger.info(f"Dry run complete — would update {updated} cards")
    else:
        logger.info(f"Done — updated {updated}, skipped {skipped}")


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
