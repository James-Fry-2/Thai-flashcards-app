"""
One-off repair for cards ingested before the text-integrity guard existed
(see src/utils/text_integrity.py) — mostly cards whose Thai text picked up a
U+FFFD from a broken PDF font ToUnicode CMap.

Writes to `cards` directly rather than through the override/correction
layer: this repairs an ingestion defect in the material value, not a user
correction (see the "Constraints: do not touch" note on card_override /
card_correction_event in the text-integrity design doc).

Usage (inside the container or with PYTHONPATH=/app):
    python scripts/repair_invalid_chars.py [--dry-run] [--batch-size N]
"""
import argparse
import asyncio
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/app")

from loguru import logger
from sqlalchemy import select

from src.config.settings import get_settings
from src.db.database import get_session_factory
from src.db.models.card import Card
from src.db.services.text_integrity_service import repair_thai_field
from src.utils.card_overrides import upsert_flag
from src.utils.current_user import current_user
from src.utils.text_integrity import find_invalid_chars, repair_non_thai_field

_TEXT_COLUMNS = (
    "thai", "example_thai", "english", "example_english",
    "romanization", "romanization_source", "romanization_paiboon",
    "romanization_rtgs", "romanization_ipa", "romanization_manual",
)


def _has_invalid_chars(card: Card) -> bool:
    for col in _TEXT_COLUMNS:
        value = getattr(card, col)
        if value and find_invalid_chars(value):
            return True
    return False


def _backup_sqlite_db() -> Path:
    """Copy the sqlite DB file to <db>.bak-<timestamp>. Raises on failure —
    the caller must not proceed with a real run without a successful backup."""
    url = get_settings().database_url
    prefix = "sqlite+aiosqlite://"
    if not url.startswith(prefix):
        raise RuntimeError(f"Non-sqlite database_url ({url!r}) — refusing to run without a file backup")

    db_path = Path(url[len(prefix):])
    if not db_path.exists():
        raise RuntimeError(f"DB file {db_path} not found")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = db_path.parent / f"{db_path.name}.bak-{stamp}"
    shutil.copy2(db_path, backup_path)
    return backup_path


async def _recompute_derived_fields(db, card: Card) -> None:
    """Mirror card_service.create_card()'s derivation from `thai` after an
    in-place repair changes it."""
    from src.db.services import embedding_service
    from src.db.services.preferences_service import get_preferences
    from src.utils.compound import compute_compound_breakdown
    from src.utils.romanization import generate_all, resolve_effective
    from src.utils.thai_analysis import analyze_thai
    from src.utils.translation_check import check_translation

    analysis = analyze_thai(card.thai)
    card.syllable_count = analysis["syllable_count"]
    card.tone_pattern = json.dumps(analysis["tone_pattern"], ensure_ascii=False)
    card.consonant_classes = json.dumps(analysis["consonant_classes"], ensure_ascii=False)
    card.has_cluster = analysis["has_cluster"]
    card.has_rare_consonant = analysis["has_rare_consonant"]
    card.has_silent_mark = analysis["has_silent_mark"]
    card.script_analysis = json.dumps(analysis["script_analysis"], ensure_ascii=False)

    breakdown, is_compound = await compute_compound_breakdown(db, card.thai, syllable_count=analysis["syllable_count"])
    card.compound_breakdown = json.dumps(breakdown, ensure_ascii=False) if breakdown is not None else None
    card.is_compound = is_compound

    try:
        translation_status, translation_candidates = await check_translation(db, card.thai, card.english)
    except Exception:
        translation_status, translation_candidates = "unverified", None
    card.translation_status = translation_status
    card.translation_candidates = (
        json.dumps(translation_candidates, ensure_ascii=False) if translation_candidates else None
    )

    schemes = generate_all(card.thai)
    card.romanization_paiboon = schemes.get("paiboon") or None
    card.romanization_rtgs = schemes.get("rtgs") or None
    card.romanization_ipa = schemes.get("ipa") or None

    prefs = await get_preferences(db)
    card.romanization = resolve_effective(
        {
            "romanization_source": card.romanization_source,
            "romanization_paiboon": card.romanization_paiboon,
            "romanization_rtgs": card.romanization_rtgs,
            "romanization_ipa": card.romanization_ipa,
            "romanization_manual": card.romanization_manual,
        },
        prefs,
    )

    await embedding_service.embed_card(db, card.id)


async def _repair_thai_or_example(db, card: Card, field: str, dry_run: bool) -> tuple[dict | None, bool]:
    """Repair one Thai-script field (thai or example_thai).

    Returns (report_entry, thai_changed) — thai_changed is only meaningful
    for field == "thai" and tells the caller whether derived columns need
    recomputing.
    """
    original = getattr(card, field)
    if not original or not find_invalid_chars(original):
        return None, False

    result, validated = await repair_thai_field(db, original, field)
    if not result.changed:
        return None, False

    if field == "thai" and result.text != card.thai:
        duplicate = await db.scalar(
            select(Card).where(
                Card.deck_id == card.deck_id, Card.thai == result.text, Card.id != card.id,
            )
        )
        if duplicate is not None:
            entry = {
                "card_id": card.id, "field": field, "original": original,
                "repaired": result.text, "validated": validated,
                "action": "skipped_duplicate_after_repair", "other_card_id": duplicate.id,
            }
            if not dry_run:
                flagged_value = json.dumps(
                    {
                        "field": field, "original": original, "other_card_id": duplicate.id,
                        "reason": "invalid_chars_duplicate_after_repair",
                    },
                    ensure_ascii=False,
                )
                await upsert_flag(db, current_user(), card.id, "other", None, flagged_value)
            return entry, False

    if result.invalid_remaining:
        action, reason = "flagged_invalid_chars", "invalid_chars"
    elif validated:
        action, reason = "repaired", None
    else:
        action, reason = "flagged_unverified_repair", "invalid_chars_unverified_repair"

    entry = {
        "card_id": card.id, "field": field, "original": original,
        "repaired": result.text, "validated": validated, "action": action,
    }

    if not dry_run:
        setattr(card, field, result.text)
        if reason:
            flagged_value = json.dumps(
                {"field": field, "original": original, "repaired": result.text, "reason": reason},
                ensure_ascii=False,
            )
            await upsert_flag(db, current_user(), card.id, "other", None, flagged_value)

    return entry, field == "thai" and result.text != original


async def _repair_one_card(db, card: Card, dry_run: bool, report: list[dict], counts: dict) -> None:
    thai_changed = False

    for field in ("thai", "example_thai"):
        entry, changed = await _repair_thai_or_example(db, card, field, dry_run)
        if entry is None:
            continue
        report.append(entry)
        counts[entry["action"]] = counts.get(entry["action"], 0) + 1
        if field == "thai":
            thai_changed = changed

    for field in ("english", "example_english", "romanization_source"):
        original = getattr(card, field)
        if not original or not find_invalid_chars(original):
            continue
        result = repair_non_thai_field(original)
        if not result.changed:
            continue
        report.append({
            "card_id": card.id, "field": field, "original": original,
            "repaired": result.text, "validated": None, "action": "repaired",
        })
        counts["repaired"] = counts.get("repaired", 0) + 1
        if not dry_run:
            setattr(card, field, result.text)

    if thai_changed and not dry_run:
        await _recompute_derived_fields(db, card)


async def repair(dry_run: bool, batch_size: int) -> None:
    if not dry_run:
        backup_path = _backup_sqlite_db()
        logger.info(f"Backed up DB to {backup_path}")

    factory = get_session_factory()

    async with factory() as db:
        result = await db.execute(select(Card).order_by(Card.id))
        all_cards = list(result.scalars().all())

    affected_ids = [c.id for c in all_cards if _has_invalid_chars(c)]
    logger.info(f"Found {len(affected_ids)} cards with invalid characters (of {len(all_cards)} total)")

    if not affected_ids:
        logger.info("Nothing to do.")
        return

    report: list[dict] = []
    counts: dict[str, int] = {}

    async with factory() as db:
        for i in range(0, len(affected_ids), batch_size):
            batch_ids = affected_ids[i : i + batch_size]
            result = await db.execute(select(Card).where(Card.id.in_(batch_ids)))
            batch = list(result.scalars().all())
            for card in batch:
                await _repair_one_card(db, card, dry_run, report, counts)

            if not dry_run:
                await db.commit()
                logger.info(f"Committed batch {i // batch_size + 1} "
                            f"({min(i + batch_size, len(affected_ids))}/{len(affected_ids)})")

    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = output_dir / f"repair_invalid_chars_{stamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    prefix = "[dry-run] " if dry_run else ""
    logger.info(f"{prefix}Wrote report to {report_path}")
    logger.info(f"Summary: {counts}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing to DB or creating a backup")
    parser.add_argument("--batch-size", type=int, default=50,
                        help="Cards per DB commit (default: 50)")
    args = parser.parse_args()

    asyncio.run(repair(dry_run=args.dry_run, batch_size=args.batch_size))
