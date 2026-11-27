"""
Pre-generate Thai audio for cards, so the first play (and Anki export) is
instant. Clips are cached under MEDIA_DIR/tts; already-generated clips are
skipped and cost nothing.

Dry run by default: reports how many clips are missing and how many
characters generating them would use. Nothing is sent to Azure.

    python scripts/generate_card_audio.py                     # whole library
    python scripts/generate_card_audio.py --deck 3            # one deck
    python scripts/generate_card_audio.py --topic 12 --speeds normal,slow
    python scripts/generate_card_audio.py --deck 3 --apply    # generate

--apply refuses to go past Azure's free 500,000 characters a month (counting
this month's usage so far) unless --allow-over-free-tier is given.
"""
import argparse
import asyncio
import sys

sys.path.insert(0, "/app")

from sqlalchemy import select

from src.config.settings import get_settings
from src.db.database import get_session_factory
from src.db.models.card import Card
from src.db.models.deck import Deck
from src.db.models.topic import CardTopic
from src.db.services import tts_service
from src.tts import is_configured

FREE_TIER_CHARS = 500_000
BATCH = 200  # cards per commit, so an interrupted run keeps what it made


async def _cards(db, args) -> list[Card]:
    stmt = select(Card).join(Deck, Deck.id == Card.deck_id).where(Deck.deleted_at.is_(None))
    if args.deck:
        stmt = stmt.where(Card.deck_id == args.deck)
    if args.upload:
        stmt = stmt.where(Card.source_upload_id == args.upload)
    if args.topic:
        stmt = stmt.join(CardTopic, CardTopic.card_id == Card.id).where(CardTopic.topic_id == args.topic)
    return list((await db.scalars(stmt.order_by(Card.id))).unique())


async def main(args) -> None:
    fields = tuple(f.strip() for f in args.fields.split(","))
    speeds = tuple(s.strip() for s in args.speeds.split(","))
    if not set(fields) <= {"thai", "example"} or not set(speeds) <= {"normal", "slow"}:
        sys.exit("--fields takes thai,example and --speeds takes normal,slow")
    settings = get_settings()

    factory = get_session_factory()
    async with factory() as db:
        cards = await _cards(db, args)
        estimate = await tts_service.ensure_card_audio(db, cards, fields, speeds, generate=False)
        usage = await tts_service.usage_summary(db)

    cost = estimate.to_generate_chars * settings.tts_price_per_million_chars / 1_000_000
    print(f"{len(cards)} cards · fields {','.join(fields)} · speeds {','.join(speeds)}")
    print(f"  already generated: {estimate.cached} clips")
    print(f"  missing:           {estimate.missing} clips, {estimate.to_generate_chars:,} characters"
          f" (about ${cost:.2f} if billed)")
    if estimate.skipped:
        print(f"  skipped:           {estimate.skipped} (no speakable Thai, or too long)")
    month_after = usage["month_chars"] + estimate.to_generate_chars
    print(f"  this month so far: {usage['month_chars']:,} characters; after this run: {month_after:,}"
          f" of {FREE_TIER_CHARS:,} free")

    if not args.apply:
        print("\nDry run: nothing generated. Add --apply to generate the missing clips.")
        return
    if not estimate.missing:
        print("\nNothing to generate.")
        return
    if not is_configured(settings):
        sys.exit("\nAZURE_SPEECH_KEY is not set; nothing generated.")
    if month_after > FREE_TIER_CHARS and not args.allow_over_free_tier:
        sys.exit(f"\nThis would go past the {FREE_TIER_CHARS:,} free characters this month. "
                 "Narrow it (--deck/--topic/--fields) or pass --allow-over-free-tier.")

    totals = {"generated": 0, "failed": 0, "chars": 0}
    done_clips = 0

    for start in range(0, len(cards), BATCH):
        async with factory() as db:
            chunk = [await db.get(Card, c.id) for c in cards[start:start + BATCH]]

            def progress(done, total):
                if done == total or done % 25 == 0:
                    print(f"  {done_clips + done}/{estimate.missing} clips", flush=True)

            result = await tts_service.ensure_card_audio(
                db, chunk, fields, speeds, generate=True, concurrency=args.concurrency, on_progress=progress
            )
            await db.commit()
        done_clips += result.generated + result.failed
        totals["generated"] += result.generated
        totals["failed"] += result.failed
        totals["chars"] += result.chars

    print(f"\nDone: generated {totals['generated']} clips ({totals['chars']:,} characters), "
          f"{totals['failed']} failed.")
    if totals["failed"]:
        print("Failed clips are retried on the next run (or the first time they're played).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--deck", type=int, help="only this deck")
    parser.add_argument("--topic", type=int, help="only cards in this topic")
    parser.add_argument("--upload", type=int, help="only cards from this upload / chapter")
    parser.add_argument("--fields", default="thai,example", help="thai,example (default both)")
    parser.add_argument("--speeds", default="normal", help="normal,slow (default normal)")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--apply", action="store_true", help="generate the missing clips")
    parser.add_argument("--allow-over-free-tier", action="store_true")
    asyncio.run(main(parser.parse_args()))
