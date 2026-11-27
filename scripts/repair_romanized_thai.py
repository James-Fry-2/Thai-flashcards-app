"""
One-off repair for cards whose Thai field holds romanization or English
instead of Thai script (textbook pages that print sentences only in
romanization; see src/db/services/thai_script_service.py).

Two steps, so what gets written is exactly what you reviewed:

    # 1. Dry run: asks Claude for the Thai script, writes nothing to the DB,
    #    saves the proposals to scripts/output/romanized_thai_<stamp>.json
    python scripts/repair_romanized_thai.py

    # 2. Apply that report (backs up the DB first; no further model calls)
    python scripts/repair_romanized_thai.py --apply scripts/output/romanized_thai_<stamp>.json

Applying sets the card's Thai, keeps the book's romanization as
romanization_source, recomputes everything derived from the Thai (analysis,
compound breakdown, translation check, romanization schemes, embedding) and
files a Triage flag on each card so the spelling gets checked. Review
history is untouched. Entries can be removed from the report (or their
"thai" edited) before applying.
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/app")

from sqlalchemy import select

from src.config.settings import get_settings
from src.db.database import get_session_factory
from src.db.models.card import Card
from src.db.models.deck import Deck
from src.db.services import thai_script_service as tss
from src.llm.registry import register_providers
from src.utils.card_overrides import upsert_flag
from src.utils.current_user import current_user

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


async def _affected(db) -> list[Card]:
    cards = await db.scalars(
        select(Card).join(Deck, Deck.id == Card.deck_id).where(Deck.deleted_at.is_(None)).order_by(Card.id)
    )
    return [c for c in cards if not tss.has_thai_script(c.thai)]


async def dry_run() -> Path:
    factory = get_session_factory()
    async with factory() as db:
        cards = await _affected(db)
        if not cards:
            print("No cards without Thai script. Nothing to do.")
            sys.exit(0)
        print(f"{len(cards)} card(s) have no Thai script. Asking for conversions…")
        results = await tss.to_thai_script(
            [{"text": c.thai, "english": c.english, "hint": c.example_thai} for c in cards]
        )

        entries = []
        for card, conv in zip(cards, results):
            entry = {"card_id": card.id, "deck_id": card.deck_id, "original": card.thai, "english": card.english}
            if conv is None:
                entry.update(action="no_conversion")
            else:
                dup = await db.scalar(
                    select(Card.id).where(Card.deck_id == card.deck_id, Card.thai == conv.thai, Card.id != card.id)
                )
                entry.update(
                    thai=conv.thai, source=conv.source, confidence=conv.confidence, note=conv.note,
                    agreement=tss.agreement(card.thai, conv.thai) if conv.source == "romanization" else None,
                    action="skip_duplicate" if dup else "convert",
                    **({"duplicate_of": dup} if dup else {}),
                )
            entries.append(entry)

    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = OUTPUT_DIR / f"romanized_thai_{stamp}.json"
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2))

    for e in entries:
        if e["action"] == "no_conversion":
            print(f"  {e['card_id']:>5}  {e['original']}  ->  (no conversion)")
            continue
        extra = f"  match {e['agreement']:.2f}" if e.get("agreement") is not None else "  (from English)"
        flag = "  LOW" if e["confidence"] == "low" else ""
        dup = f"  DUPLICATE of {e['duplicate_of']}" if e["action"] == "skip_duplicate" else ""
        print(f"  {e['card_id']:>5}  {e['original']}  ->  {e['thai']}{extra}{flag}{dup}")
        if e.get("note"):
            print(f"         note: {e['note']}")
    print(f"\nReport: {path}\nNothing written to the database. Review, then run with --apply {path}")
    return path


async def apply(report_path: Path) -> None:
    from scripts.repair_invalid_chars import _backup_sqlite_db, _recompute_derived_fields

    entries = [e for e in json.loads(report_path.read_text()) if e.get("action") == "convert"]
    if not entries:
        print("Report has no entries to convert.")
        return

    factory = get_session_factory()
    async with factory() as db:
        # Re-check each card still has the value the report was made from.
        cards = {}
        for e in entries:
            card = await db.get(Card, e["card_id"])
            if card is None or card.thai != e["original"]:
                print(f"  {e['card_id']}: changed since the report, skipping")
                continue
            if not tss.has_thai_script(e["thai"]):
                print(f"  {e['card_id']}: report value {e['thai']!r} has no Thai script, skipping")
                continue
            cards[e["card_id"]] = (card, e)

        print(f"About to convert {len(cards)} card(s) (of {len(entries)} in the report).")
        backup = _backup_sqlite_db()
        print(f"Backed up database to {backup}")

        for card, e in cards.values():
            if e.get("source") == "romanization" and not card.romanization_source:
                card.romanization_source = e["original"]
            card.thai = e["thai"]
            await db.flush()
            await _recompute_derived_fields(db, card)
            await upsert_flag(db, current_user(), card.id, "other", None, json.dumps({
                "field": "thai", "original": e["original"], "repaired": e["thai"],
                "reason": "converted_to_thai_script", "note": e.get("note") or "",
            }, ensure_ascii=False))
            print(f"  {card.id}: {e['original']} -> {e['thai']}")

        await db.commit()
    print(f"Done: {len(cards)} card(s) converted and flagged in Triage.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", type=Path, metavar="REPORT", help="apply a dry-run report")
    args = parser.parse_args()
    register_providers(get_settings())
    if args.apply:
        asyncio.run(apply(args.apply))
    else:
        asyncio.run(dry_run())


if __name__ == "__main__":
    main()
