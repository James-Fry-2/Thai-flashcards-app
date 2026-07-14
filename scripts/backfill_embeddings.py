"""
Backfill embeddings for cards, topics, and tags.

Usage (inside the container or with PYTHONPATH=/app):
    python scripts/backfill_embeddings.py [--cards] [--topics] [--tags] [--all]
                                          [--dry-run] [--force] [--batch-size N]

If none of --cards/--topics/--tags/--all is given, defaults to --all.
"""
import argparse
import asyncio
import sys
import time

sys.path.insert(0, "/app")

from loguru import logger
from sqlalchemy import select

from src.db.database import get_session_factory
from src.db.models.card import Card
from src.db.models.embeddings import CardEmbedding, TagEmbedding, TopicEmbedding
from src.db.models.tag import Tag
from src.db.models.topic import Topic
from src.db.services.embedding_service import (
    _card_text,
    _is_stale,
    _tag_text,
    _to_blob,
    _topic_text,
    embed_cards_batch,
)
from src.utils.embeddings import embed_batch, text_hash as compute_hash
from src.config.settings import get_settings
from datetime import datetime, timezone


async def backfill_cards(dry_run: bool, force: bool, batch_size: int) -> None:
    factory = get_session_factory()
    settings = get_settings()

    async with factory() as db:
        cards_result = await db.execute(
            select(Card).where(Card.thai.isnot(None), Card.thai != "").order_by(Card.id)
        )
        all_cards = cards_result.scalars().all()

        existing_result = await db.execute(select(CardEmbedding))
        existing = {e.card_id: e for e in existing_result.scalars().all()}

    needs_embed = []
    for card in all_cards:
        text = _card_text(card)
        rec = existing.get(card.id)
        if force or rec is None or _is_stale(rec, text):
            needs_embed.append(card)

    total = len(needs_embed)
    logger.info(f"Cards: {total} need embedding (out of {len(all_cards)} total)")

    if dry_run:
        for card in needs_embed[:10]:
            logger.info(f"  [dry-run] id={card.id}  {repr(card.thai)[:40]:40s}  → would embed")
        if total > 10:
            logger.info(f"  ... and {total - 10} more")
        return

    embedded = 0
    failed_total: list[int] = []
    t0 = time.perf_counter()

    async with factory() as db:
        for i in range(0, total, batch_size):
            batch = needs_embed[i: i + batch_size]
            card_ids = [c.id for c in batch]
            result = await embed_cards_batch(db, card_ids)
            await db.commit()
            embedded += result["embedded"]
            failed_total.extend(result["failed"])
            logger.info(
                f"Embedded {min(i + batch_size, total)}/{total} cards "
                f"({result['embedded']} this batch, {result['skipped']} skipped, "
                f"{len(result['failed'])} failed)"
            )

    elapsed = time.perf_counter() - t0
    avg_ms = (elapsed / embedded * 1000) if embedded else 0
    logger.info(
        f"Cards done — embedded {embedded}, failed {len(failed_total)}, "
        f"total {elapsed:.1f}s, avg {avg_ms:.1f}ms/card"
    )
    if failed_total:
        logger.warning(f"Failed card ids: {failed_total}")


async def backfill_topics(dry_run: bool, force: bool, batch_size: int) -> None:
    factory = get_session_factory()

    async with factory() as db:
        topics_result = await db.execute(select(Topic).order_by(Topic.id))
        all_topics = topics_result.scalars().all()

        existing_result = await db.execute(select(TopicEmbedding))
        existing = {e.topic_id: e for e in existing_result.scalars().all()}

    needs_embed = []
    for topic in all_topics:
        text = _topic_text(topic)
        rec = existing.get(topic.id)
        if force or rec is None or _is_stale(rec, text):
            needs_embed.append(topic)

    total = len(needs_embed)
    logger.info(f"Topics: {total} need embedding (out of {len(all_topics)} total)")

    if dry_run:
        for t in needs_embed[:10]:
            logger.info(f"  [dry-run] id={t.id}  {t.name!r:40s}  → would embed")
        if total > 10:
            logger.info(f"  ... and {total - 10} more")
        return

    embedded = 0
    failed_total: list[int] = []
    t0 = time.perf_counter()
    settings = get_settings()
    now = datetime.now(timezone.utc)

    async with factory() as db:
        existing_result = await db.execute(select(TopicEmbedding))
        existing = {e.topic_id: e for e in existing_result.scalars().all()}

        for i in range(0, total, batch_size):
            batch = needs_embed[i: i + batch_size]
            texts = [_topic_text(t) for t in batch]
            vecs = embed_batch(texts)
            for topic, text, vec in zip(batch, texts, vecs):
                if vec is None:
                    failed_total.append(topic.id)
                    continue
                rec = existing.get(topic.id)
                if rec:
                    rec.model_name = settings.embedding_model
                    rec.embedding = _to_blob(vec)
                    rec.text_hash = compute_hash(text)
                    rec.updated_at = now
                else:
                    db.add(TopicEmbedding(
                        topic_id=topic.id,
                        model_name=settings.embedding_model,
                        embedding=_to_blob(vec),
                        text_hash=compute_hash(text),
                        updated_at=now,
                    ))
                embedded += 1
            await db.commit()
            logger.info(f"Embedded {min(i + batch_size, total)}/{total} topics")

    elapsed = time.perf_counter() - t0
    avg_ms = (elapsed / embedded * 1000) if embedded else 0
    logger.info(
        f"Topics done — embedded {embedded}, failed {len(failed_total)}, "
        f"total {elapsed:.1f}s, avg {avg_ms:.1f}ms/topic"
    )


async def backfill_tags(dry_run: bool, force: bool, batch_size: int) -> None:
    factory = get_session_factory()

    async with factory() as db:
        tags_result = await db.execute(select(Tag).order_by(Tag.id))
        all_tags = tags_result.scalars().all()

        existing_result = await db.execute(select(TagEmbedding))
        existing = {e.tag_id: e for e in existing_result.scalars().all()}

    needs_embed = []
    for tag in all_tags:
        text = _tag_text(tag)
        rec = existing.get(tag.id)
        if force or rec is None or _is_stale(rec, text):
            needs_embed.append(tag)

    total = len(needs_embed)
    logger.info(f"Tags: {total} need embedding (out of {len(all_tags)} total)")

    if dry_run:
        for t in needs_embed[:10]:
            logger.info(f"  [dry-run] id={t.id}  {t.name!r:40s}  → would embed")
        if total > 10:
            logger.info(f"  ... and {total - 10} more")
        return

    embedded = 0
    failed_total: list[int] = []
    t0 = time.perf_counter()
    settings = get_settings()
    now = datetime.now(timezone.utc)

    async with factory() as db:
        existing_result = await db.execute(select(TagEmbedding))
        existing = {e.tag_id: e for e in existing_result.scalars().all()}

        for i in range(0, total, batch_size):
            batch = needs_embed[i: i + batch_size]
            texts = [_tag_text(t) for t in batch]
            vecs = embed_batch(texts)
            for tag, text, vec in zip(batch, texts, vecs):
                if vec is None:
                    failed_total.append(tag.id)
                    continue
                rec = existing.get(tag.id)
                if rec:
                    rec.model_name = settings.embedding_model
                    rec.embedding = _to_blob(vec)
                    rec.text_hash = compute_hash(text)
                    rec.updated_at = now
                else:
                    db.add(TagEmbedding(
                        tag_id=tag.id,
                        model_name=settings.embedding_model,
                        embedding=_to_blob(vec),
                        text_hash=compute_hash(text),
                        updated_at=now,
                    ))
                embedded += 1
            await db.commit()
            logger.info(f"Embedded {min(i + batch_size, total)}/{total} tags")

    elapsed = time.perf_counter() - t0
    avg_ms = (elapsed / embedded * 1000) if embedded else 0
    logger.info(
        f"Tags done — embedded {embedded}, failed {len(failed_total)}, "
        f"total {elapsed:.1f}s, avg {avg_ms:.1f}ms/tag"
    )


async def main(
    do_cards: bool,
    do_topics: bool,
    do_tags: bool,
    dry_run: bool,
    force: bool,
    batch_size: int,
) -> None:
    if not any([do_cards, do_topics, do_tags]):
        do_cards = do_topics = do_tags = True

    logger.info(
        f"backfill_embeddings  dry_run={dry_run}  force={force}  batch_size={batch_size}"
    )
    logger.info(f"Model: {get_settings().embedding_model}")

    t_start = time.perf_counter()

    if do_cards:
        await backfill_cards(dry_run=dry_run, force=force, batch_size=batch_size)
    if do_topics:
        await backfill_topics(dry_run=dry_run, force=force, batch_size=batch_size)
    if do_tags:
        await backfill_tags(dry_run=dry_run, force=force, batch_size=batch_size)

    total_elapsed = time.perf_counter() - t_start
    logger.info(f"Total wall time: {total_elapsed:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cards", action="store_true", help="Backfill card embeddings")
    parser.add_argument("--topics", action="store_true", help="Backfill topic embeddings")
    parser.add_argument("--tags", action="store_true", help="Backfill tag embeddings")
    parser.add_argument("--all", dest="all_", action="store_true", default=True, help="Backfill all (default)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be embedded without writing")
    parser.add_argument("--force", action="store_true", help="Re-embed even if embedding is up-to-date")
    parser.add_argument("--batch-size", type=int, default=64, help="Items per batch (default: 64)")
    args = parser.parse_args()

    explicit = args.cards or args.topics or args.tags
    asyncio.run(main(
        do_cards=args.cards or (not explicit),
        do_topics=args.topics or (not explicit),
        do_tags=args.tags or (not explicit),
        dry_run=args.dry_run,
        force=args.force,
        batch_size=args.batch_size,
    ))
