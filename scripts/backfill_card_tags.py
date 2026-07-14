"""
Backfill topic + tag assignments for cards that have no CardTopic entry.

Usage (inside the container or with PYTHONPATH=/app):
    python scripts/backfill_card_tags.py [--dry-run] [--batch-size N]

--dry-run calls the LLM (cannot skip that) but skips all DB writes;
logs what *would* be assigned instead.
"""
import argparse
import asyncio
import sys

sys.path.insert(0, "/app")

from loguru import logger
from sqlalchemy import select, not_, exists

from src.db.database import get_session_factory
from src.db.models.card import Card
from src.db.models.topic import CardTopic


async def backfill(dry_run: bool, batch_size: int, deck_id: int | None = None) -> None:
    from src.config.settings import get_settings
    from src.llm.registry import register_providers
    register_providers(get_settings())

    factory = get_session_factory()

    async with factory() as db:
        stmt = (
            select(Card)
            .where(
                not_(exists(select(CardTopic.card_id).where(CardTopic.card_id == Card.id)))
            )
            .order_by(Card.id)
        )
        if deck_id is not None:
            stmt = stmt.where(Card.deck_id == deck_id)
        result = await db.execute(stmt)
        cards = result.scalars().all()

    logger.info(f"Found {len(cards)} untagged cards (no CardTopic entry)")

    if not cards:
        logger.info("Nothing to do.")
        return

    total_tagged = 0
    total_failed: list[int] = []
    all_topics_created: list[str] = []
    all_tags_created: list[str] = []

    card_ids = [c.id for c in cards]

    for i in range(0, len(card_ids), batch_size):
        batch_ids = card_ids[i : i + batch_size]
        batch_num = i // batch_size + 1
        logger.info(f"Batch {batch_num}: processing card ids {batch_ids[0]}–{batch_ids[-1]}")

        if dry_run:
            # Call the LLM but log instead of writing
            from src.db.services.card_tagging_service import (
                get_existing_topic_names,
                _tag_batch,
            )
            async with factory() as db:
                existing_topics = await get_existing_topic_names(db)
                from src.llm.registry import get_provider, LLMTask
                from src.llm.prompts.card_tagging import build_card_tagging_messages
                import json
                from json_repair import repair_json

                batch_cards_result = await db.execute(
                    select(Card).where(Card.id.in_(batch_ids))
                )
                batch_cards = {c.id: c for c in batch_cards_result.scalars().all()}
                card_dicts = [
                    {
                        "id": c.id,
                        "thai": c.thai,
                        "english": c.english,
                        **({"example_thai": c.example_thai} if c.example_thai else {}),
                    }
                    for c in batch_cards.values()
                ]

                provider = get_provider(LLMTask.CARD_TAGGING)
                messages = build_card_tagging_messages(card_dicts, existing_topics)
                response = await provider.complete(messages)
                raw_json = response.text.strip()
                if raw_json.startswith("```"):
                    raw_json = raw_json.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

                try:
                    items = json.loads(raw_json)
                except json.JSONDecodeError:
                    try:
                        items = json.loads(repair_json(raw_json))
                    except Exception:
                        logger.warning(f"[dry-run] Batch {batch_num}: JSON parse failed")
                        total_failed.extend(batch_ids)
                        continue

                if not isinstance(items, list):
                    logger.warning(f"[dry-run] Batch {batch_num}: non-list response")
                    total_failed.extend(batch_ids)
                    continue

                responded: set[int] = set()
                for item in items:
                    card_id = item.get("id")
                    if not isinstance(card_id, int) or card_id not in batch_cards:
                        continue
                    responded.add(card_id)
                    card = batch_cards[card_id]
                    topic = item.get("topic", "")
                    tags = [t for t in item.get("tags", []) if isinstance(t, str)][:5]
                    logger.info(
                        f"[dry-run] id={card_id} thai={card.thai!r:20s} "
                        f"→ topic={topic!r}  tags={tags}"
                    )
                    total_tagged += 1

                for card_id in batch_ids:
                    if card_id not in responded:
                        logger.warning(f"[dry-run] id={card_id}: no response from LLM")
                        total_failed.append(card_id)
        else:
            async with factory() as db:
                from src.db.services.card_tagging_service import _tag_batch
                result = await _tag_batch(db, batch_ids)
                await db.commit()

            total_tagged += result["tagged"]
            total_failed.extend(result["failed"])
            all_topics_created.extend(result["topics_created"])
            all_tags_created.extend(result["tags_created"])

            logger.info(
                f"Batch {batch_num}: tagged={result['tagged']} "
                f"failed={result['failed']} "
                f"new_topics={result['topics_created']} "
                f"new_tags={result['tags_created']}"
            )

    # Final summary
    mode = "[dry-run] " if dry_run else ""
    logger.info(
        f"{mode}Done — total_processed={len(card_ids)} "
        f"tagged={total_tagged} "
        f"failed={len(total_failed)} "
        f"topics_created={list(dict.fromkeys(all_topics_created))} "
        f"tags_created={list(dict.fromkeys(all_tags_created))}"
    )
    if total_failed:
        logger.warning(f"{mode}Failed card ids: {total_failed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Call LLM but skip DB writes — logs what would be assigned",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Cards per LLM call (default: 25)",
    )
    parser.add_argument(
        "--deck-id",
        type=int,
        default=None,
        help="Only process cards from this deck",
    )
    args = parser.parse_args()

    asyncio.run(backfill(dry_run=args.dry_run, batch_size=args.batch_size, deck_id=args.deck_id))
