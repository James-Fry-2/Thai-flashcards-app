"""
Detect confusable card pairs — sound-alike (phonetic/tone) and look-alike
(orthographic) — and link them with link_type="confusable".

Deterministic, offline batch pass (see src/utils/confusables.py). Not run on
the card-creation hot path.

Usage:
    python scripts/detect_confusables.py [--dry-run] [--batch-size N] [--no-clear]

Flags:
    --dry-run    Report what would be linked, grouped by reason, without writing.
    --batch-size N   Pairs per commit (default: 200).
    --no-clear   Skip clearing existing auto-detected confusable links first.
                 (Default clears link_type="confusable" AND note IS NOT NULL —
                 user-made confusable links, which have note=NULL, are never touched.)
"""
import argparse
import asyncio
import json
import sys
from collections import Counter

sys.path.insert(0, "/app")

from loguru import logger
from sqlalchemy import delete, select

from src.config.settings import get_settings
from src.db.database import get_session_factory
from src.db.models.card import Card
from src.db.models.card_link import CardLink
from src.db.services import link_service
from src.utils.confusables import ConfusableCard, generate_candidate_pairs, is_confusable


async def _clear_auto_links(db) -> int:
    result = await db.execute(
        delete(CardLink).where(
            CardLink.link_type == "confusable",
            CardLink.note.isnot(None),
        )
    )
    return result.rowcount or 0


async def detect(dry_run: bool, batch_size: int, clear: bool) -> None:
    settings = get_settings()
    factory = get_session_factory()

    async with factory() as db:
        if clear and not dry_run:
            cleared = await _clear_auto_links(db)
            await db.commit()
            logger.info(f"Cleared {cleared} existing auto-detected confusable links")

        result = await db.execute(
            select(Card.id, Card.thai, Card.romanization_ipa, Card.tone_pattern)
            .where(Card.thai.isnot(None))
            .where(Card.thai != "")
        )
        rows = result.all()

    logger.info(f"Loaded {len(rows)} cards")
    if not rows:
        logger.info("Nothing to do.")
        return

    card_ids = [row.id for row in rows]
    cards: list[ConfusableCard] = [
        {
            "thai": row.thai,
            "romanization_ipa": row.romanization_ipa,
            "tone_pattern": json.loads(row.tone_pattern) if row.tone_pattern else None,
        }
        for row in rows
    ]

    candidate_pairs = generate_candidate_pairs(cards)
    logger.info(f"Blocked {len(candidate_pairs)} candidate pairs from {len(cards)} cards")

    linked_pairs: list[tuple[int, int, str]] = []
    reason_counts: Counter = Counter()

    for a_idx, b_idx in candidate_pairs:
        reason = is_confusable(cards[a_idx], cards[b_idx], settings)
        if reason is None:
            continue
        linked_pairs.append((card_ids[a_idx], card_ids[b_idx], reason))
        reason_counts[reason] += 1

    if dry_run:
        logger.info(f"[dry-run] Would link {len(linked_pairs)} confusable pairs:")
        for reason, count in reason_counts.most_common():
            logger.info(f"  {reason}: {count}")
        sample = linked_pairs[:10]
        if sample:
            logger.info("Sample:")
            id_to_thai = {cid: c["thai"] for cid, c in zip(card_ids, cards)}
            for a_id, b_id, reason in sample:
                logger.info(f"  {id_to_thai[a_id]} <-> {id_to_thai[b_id]}  ({reason})")
        return

    linked = 0
    async with factory() as db:
        for i in range(0, len(linked_pairs), batch_size):
            batch = linked_pairs[i : i + batch_size]
            for a_id, b_id, reason in batch:
                await link_service.create_link(db, a_id, b_id, "confusable", note=reason)
                linked += 1
            await db.commit()
            logger.info(
                f"Committed batch {i // batch_size + 1} "
                f"({min(i + batch_size, len(linked_pairs))}/{len(linked_pairs)})"
            )

    logger.info(f"Done — scored {len(candidate_pairs)} candidates, linked {linked} pairs:")
    for reason, count in reason_counts.most_common():
        logger.info(f"  {reason}: {count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument(
        "--no-clear",
        dest="clear",
        action="store_false",
        help="Skip clearing existing auto-detected confusable links first",
    )
    args = parser.parse_args()

    asyncio.run(detect(dry_run=args.dry_run, batch_size=args.batch_size, clear=args.clear))
