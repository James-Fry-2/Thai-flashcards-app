"""
Staged, resumable upload pipeline.

Stages for single / chapter_child uploads (stored in upload.stage):
  queued → ocr → generating → tagging → complete

Stages for book_parent uploads:
  queued → splitting → awaiting_confirmation → dispatching → complete

Each stage commits its progress so a restart loses at most the in-flight step.
"""
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Optional
from loguru import logger
from sqlalchemy import select, delete, func

from pydantic import BaseModel, ValidationError

from src.config.settings import get_settings
from src.db.models.upload import Upload
from src.db.models.upload_page import UploadPage
from src.db.models.card import Card
from src.ocr.pipeline import run_ocr_pipeline
from src.utils.file_parser import prepare_file_for_ocr, extract_pdf_text_layer, get_pdf_page_count, slice_pdf
from src.llm.registry import get_provider, LLMTask
from src.llm.prompts.card_generation import build_card_generation_messages
from src.db.services.card_service import bulk_create_cards, create_card
from src.db.services import card_tagging_service


class CardItem(BaseModel):
    thai: str
    romanization: Optional[str] = None   # LLM-copied from source material → romanization_source
    english: str
    example_thai: Optional[str] = None
    example_english: Optional[str] = None
    card_type: str = "vocab"


async def process_upload(db, upload: Upload) -> None:
    """
    Run (or resume) the staged pipeline for the given upload.
    Branches on upload.kind:
      - 'book_parent' → parent splitting/dispatching pipeline
      - 'single' / 'chapter_child' → normal OCR → generate → tag pipeline
    """
    if upload.kind == "book_parent":
        await _process_book_parent(db, upload)
    else:
        await _process_child_or_single(db, upload)


# ---------------------------------------------------------------------------
# Normal pipeline (single + chapter_child)
# ---------------------------------------------------------------------------

async def _process_child_or_single(db, upload: Upload) -> None:
    settings = get_settings()

    if upload.stage in ("queued", "ocr"):
        await _stage_ocr(db, upload, settings)

    if upload.stage == "generating":
        await _stage_generating(db, upload)

    if upload.stage == "tagging":
        await _stage_tagging(db, upload)


# ---------------------------------------------------------------------------
# Book-parent pipeline
# ---------------------------------------------------------------------------

async def _process_book_parent(db, upload: Upload) -> None:
    settings = get_settings()

    if upload.stage in ("queued", "splitting"):
        if upload.chapter_map is None:
            # Single PDF — need to detect chapters
            await _stage_splitting(db, upload, settings)
        else:
            # Multi-file — map already built by the endpoint; go straight to dispatching
            upload.stage = "dispatching"
            await db.commit()

    # After splitting, if confirmation is required → stall; worker skips awaiting_confirmation
    if upload.stage == "awaiting_confirmation":
        return

    if upload.stage == "dispatching":
        await _stage_dispatching(db, upload, settings)

    # complete is set by _stage_dispatching


async def _stage_splitting(db, upload: Upload, settings) -> None:
    """Build the chapter_map from the single uploaded PDF using the ensemble detector."""
    upload.stage = "splitting"
    await db.commit()

    upload_dir = Path(settings.media_dir) / "uploads" / str(upload.id)
    pdf_files = list(upload_dir.glob("*.pdf")) + list(upload_dir.glob("*.PDF"))
    if not pdf_files:
        raise FileNotFoundError(f"No PDF found in upload dir {upload_dir}")
    src_path = pdf_files[0]

    total_pages = get_pdf_page_count(src_path)
    if total_pages is None or total_pages == 0:
        raise RuntimeError(f"Could not determine page count for {src_path}")

    from src.utils.chapter_signals import detect_chapters
    chapter_map_dict, page_signals_dict = await asyncio.to_thread(
        detect_chapters, src_path, settings
    )

    # Ensure page_count is set from the actual PDF
    chapter_map_dict["page_count"] = total_pages

    upload.chapter_map = json.dumps(chapter_map_dict)
    upload.page_signals = json.dumps(page_signals_dict) if page_signals_dict else None
    upload.total_pages = total_pages

    n_boundaries = len(chapter_map_dict.get("boundaries", []))
    if upload.requires_confirmation:
        upload.stage = "awaiting_confirmation"
        upload.status = "awaiting_confirmation"
    else:
        upload.stage = "dispatching"

    await db.commit()
    logger.info(
        f"Upload {upload.id} (book_parent): detected {n_boundaries} boundaries "
        f"(requires_confirmation={upload.requires_confirmation})"
    )


async def _stage_dispatching(db, upload: Upload, settings) -> None:
    """Create chapter_child uploads for each includable boundary not yet dispatched."""
    upload.stage = "dispatching"
    await db.commit()

    raw = upload.chapter_map or "[]"
    entries, is_new_fmt = _parse_chapter_map_for_dispatch(raw)

    if not entries:
        upload.stage = "complete"
        upload.status = "done"
        await db.commit()
        return

    upload_dir = Path(settings.media_dir) / "uploads" / str(upload.id)
    pdf_files = list(upload_dir.glob("*.pdf")) + list(upload_dir.glob("*.PDF"))
    if not pdf_files:
        raise FileNotFoundError(f"No PDF found in upload dir {upload_dir}")
    src_path = pdf_files[0]

    page_count = upload.total_pages or 0
    map_changed = False

    for i, entry in enumerate(entries):
        if entry.get("child_upload_id") is not None:
            continue  # Idempotent skip — already dispatched

        if is_new_fmt:
            # New format: skip include:false spans (front matter, appendices)
            if not entry.get("include", True):
                continue

            # Derive page_end from the next boundary regardless of its include flag
            next_start_1idx = entries[i + 1]["page_start"] if i + 1 < len(entries) else None
            page_end_1idx = (next_start_1idx - 1) if next_start_1idx else max(page_count, 1)
            fitz_start = entry["page_start"] - 1  # 1-indexed → 0-indexed
            fitz_end = page_end_1idx - 1

            chapter_label = entry.get("title_en") or entry.get("title_th") or f"Chapter {entry['idx'] + 1}"
            section_label = entry.get("title_th") if entry.get("title_en") else None
            source_filename = None
        else:
            # Legacy list format (multi-file imports)
            page_start = entry["page_start"]
            page_end = entry["page_end"]
            fitz_start = page_start
            fitz_end = page_end
            chapter_label = entry.get("chapter_label") or f"Chapter {entry['idx'] + 1}"
            section_label = entry.get("section_label")
            source_filename = entry.get("source_filename")

        child_filename = f"chapter_{entry['idx']:03d}.pdf"
        child = Upload(
            filename=child_filename,
            file_type="pdf",
            kind="chapter_child",
            parent_upload_id=upload.id,
            deck_id=upload.deck_id,
            source_title=upload.source_title,
            chapter_label=chapter_label,
            section_label=section_label,
            status="pending",
            stage="queued",
        )
        db.add(child)
        await db.flush()

        child_dir = Path(settings.media_dir) / "uploads" / str(child.id)
        child_dir.mkdir(parents=True, exist_ok=True)
        dst_path = child_dir / child_filename

        if source_filename and fitz_end == -1:
            # Multi-file import: copy the original chapter file
            original = upload_dir / source_filename
            if not original.exists():
                raise FileNotFoundError(f"Source file not found: {original}")
            import shutil
            await asyncio.to_thread(shutil.copy2, str(original), str(dst_path))
        else:
            await asyncio.to_thread(slice_pdf, src_path, fitz_start, fitz_end, dst_path)

        entry["child_upload_id"] = child.id
        map_changed = True
        logger.info(
            f"Upload {upload.id}: dispatched '{chapter_label}' "
            f"(fitz pages {fitz_start}–{fitz_end}) → child {child.id}"
        )

    if map_changed:
        if is_new_fmt:
            parsed = json.loads(raw)
            parsed["boundaries"] = entries
            upload.chapter_map = json.dumps(parsed)
        else:
            upload.chapter_map = json.dumps(entries)

    upload.stage = "complete"
    upload.status = "done"
    await db.commit()


def _parse_chapter_map_for_dispatch(raw: str) -> tuple[list, bool]:
    """Parse chapter_map JSON; returns (entries, is_new_format)."""
    try:
        data = json.loads(raw)
    except Exception:
        return [], False
    if isinstance(data, list):
        return data, False
    return data.get("boundaries", []), True


# ---------------------------------------------------------------------------
# Stage: OCR (with text-layer skip for digital PDFs, §6)
# ---------------------------------------------------------------------------

async def _stage_ocr(db, upload: Upload, settings) -> None:
    upload.stage = "ocr"
    await db.commit()

    file_path = Path(settings.media_dir) / "uploads" / str(upload.id) / upload.filename
    if not file_path.exists():
        raise FileNotFoundError(f"Upload file not found: {file_path}")

    # If raw_text already set and all pages are terminal, OCR is done — advance.
    if upload.raw_text is not None:
        all_pages = list(await db.scalars(
            select(UploadPage).where(UploadPage.upload_id == upload.id)
        ))
        if all_pages and all(p.status in ("done", "failed") for p in all_pages):
            logger.info(f"Upload {upload.id}: OCR already complete, skipping to generating")
            upload.stage = "generating"
            await db.commit()
            return

    # §6 text-layer extraction for PDFs
    text_layer: list[str] = []
    if upload.filename.lower().endswith(".pdf"):
        text_layer = await asyncio.to_thread(extract_pdf_text_layer, file_path)

    file_bytes = file_path.read_bytes()
    image_pages = await asyncio.to_thread(prepare_file_for_ocr, file_bytes, upload.filename)

    # Idempotently create page rows for any page not yet recorded
    existing_rows = list(await db.scalars(
        select(UploadPage).where(UploadPage.upload_id == upload.id)
    ))
    existing_indices = {p.page_index for p in existing_rows}

    for idx in range(len(image_pages)):
        if idx not in existing_indices:
            db.add(UploadPage(upload_id=upload.id, page_index=idx, status="pending"))

    upload.total_pages = len(image_pages)
    await db.commit()

    # Build a fresh page-index → row map after the flush
    page_map: dict[int, UploadPage] = {}
    for row in await db.scalars(select(UploadPage).where(UploadPage.upload_id == upload.id)):
        page_map[row.page_index] = row

    min_chars = settings.pdf_text_min_chars
    last_engine = "claude_vision"
    last_confidence = 1.0

    for idx, (image_bytes, media_type) in enumerate(image_pages):
        page = page_map.get(idx)
        if page is None:
            continue
        if page.status == "done":
            last_engine = page.engine_used or last_engine
            last_confidence = page.confidence if page.confidence is not None else last_confidence
            continue

        # §6: use text layer if sufficient, skip rasterize + OCR
        layer_text = text_layer[idx] if idx < len(text_layer) else ""
        if len(layer_text) >= min_chars:
            page.text = layer_text
            page.engine_used = "pdf_text"
            page.confidence = 1.0
            page.status = "done"
            last_engine = "pdf_text"
            last_confidence = 1.0
        else:
            try:
                result = await run_ocr_pipeline(image_bytes, media_type)
                page.text = result.text
                page.engine_used = result.engine_used
                page.confidence = result.confidence
                page.status = "done"
                last_engine = result.engine_used
                last_confidence = result.confidence
            except Exception as exc:
                logger.warning(f"Upload {upload.id} page {idx} OCR failed: {exc}")
                page.status = "failed"

        # Update progress count after each page
        upload.pages_processed = await db.scalar(
            select(func.count()).where(
                UploadPage.upload_id == upload.id,
                UploadPage.status == "done",
            )
        ) or 0
        await db.commit()

    # Final accurate counts
    upload.pages_processed = await db.scalar(
        select(func.count()).where(
            UploadPage.upload_id == upload.id,
            UploadPage.status == "done",
        )
    ) or 0

    failed_count = await db.scalar(
        select(func.count()).where(
            UploadPage.upload_id == upload.id,
            UploadPage.status == "failed",
        )
    ) or 0

    # Assemble raw_text from done pages in order
    done_pages = list(await db.scalars(
        select(UploadPage)
        .where(UploadPage.upload_id == upload.id, UploadPage.status == "done")
        .order_by(UploadPage.page_index)
    ))
    raw_text = "\n\n".join(p.text for p in done_pages if p.text)

    upload.raw_text = raw_text
    upload.ocr_engine_used = last_engine
    upload.ocr_confidence = last_confidence

    if raw_text.strip():
        upload.text_hash = hashlib.sha256(raw_text.encode()).hexdigest()

    if failed_count:
        upload.error_message = f"{failed_count} page(s) could not be read"

    if not raw_text.strip():
        upload.status = "done"
        upload.stage = "complete"
        upload.cards_created = 0
        await db.commit()
        logger.info(f"Upload {upload.id}: no OCR text extracted (failed={failed_count})")
        return

    upload.stage = "generating"
    await db.commit()


# ---------------------------------------------------------------------------
# Stage: card generation (with chunked generation safety net, §7)
# ---------------------------------------------------------------------------

async def _stage_generating(db, upload: Upload) -> None:
    # Idempotency: delete any cards from a prior partial attempt before regenerating.
    await db.execute(delete(Card).where(Card.source_upload_id == upload.id))
    await db.commit()

    raw_text = upload.raw_text or ""

    # Dedup: clone from a prior upload with the same hash
    if upload.text_hash:
        prior = await db.scalar(
            select(Upload).where(
                Upload.text_hash == upload.text_hash,
                Upload.cards_created > 0,
                Upload.id != upload.id,
            )
        )
        if prior and upload.deck_id:
            logger.info(
                f"Upload {upload.id}: duplicate of upload {prior.id}, "
                f"cloning {prior.cards_created} cards"
            )
            source_cards = list(await db.scalars(
                select(Card).where(Card.source_upload_id == prior.id)
            ))
            cloned = []
            for card in source_cards:
                new_card = await create_card(
                    db,
                    deck_id=upload.deck_id,
                    thai=card.thai,
                    english=card.english,
                    romanization=card.romanization,
                    romanization_source=card.romanization_source,
                    romanization_paiboon=card.romanization_paiboon,
                    romanization_rtgs=card.romanization_rtgs,
                    romanization_ipa=card.romanization_ipa,
                    romanization_manual=card.romanization_manual,
                    example_thai=card.example_thai,
                    example_english=card.example_english,
                    card_type=card.card_type,
                    source_upload_id=upload.id,
                )
                await card_tagging_service.copy_tags_and_topic(db, card.id, new_card.id)
                cloned.append(new_card)
            upload.cards_created = len(cloned)
            upload.stage = "tagging"
            await db.commit()
            return

    settings = get_settings()
    cards_data = await _generate_cards_chunked(raw_text, settings.card_generation_char_budget)

    from src.db.services.preferences_service import get_preferences
    prefs = await get_preferences(db)
    await asyncio.to_thread(_fill_romanization, cards_data, prefs)

    created = []
    if upload.deck_id and cards_data:
        created = await bulk_create_cards(
            db,
            deck_id=upload.deck_id,
            cards_data=cards_data,
            source_upload_id=upload.id,
        )

    upload.cards_created = len(created)
    upload.stage = "tagging"
    await db.commit()
    logger.info(f"Upload {upload.id}: {upload.cards_created} cards created via {upload.ocr_engine_used}")


# ---------------------------------------------------------------------------
# Stage: tagging (best-effort — never flips status to failed)
# ---------------------------------------------------------------------------

async def _stage_tagging(db, upload: Upload) -> None:
    cards = list(await db.scalars(select(Card).where(Card.source_upload_id == upload.id)))
    if cards:
        try:
            tagging_result = await card_tagging_service.tag_cards(db, [c.id for c in cards])
            await db.commit()
            logger.info(
                f"Upload {upload.id}: tagged {tagging_result['tagged']} cards "
                f"(topics_created={tagging_result['topics_created']}, "
                f"tags_created={tagging_result['tags_created']}, "
                f"failed={tagging_result['failed']})"
            )
        except Exception as tag_exc:
            logger.warning(f"Upload {upload.id}: tagging failed (cards still created): {tag_exc}")

    upload.stage = "complete"
    upload.status = "done"
    await db.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fill_romanization(cards_data: list, prefs) -> None:
    """Compute all romanization schemes for each card and resolve the effective value."""
    from src.utils.romanization import generate_all, resolve_effective
    for card in cards_data:
        source = card.pop("romanization", None) or None
        card["romanization_source"] = source

        thai = card.get("thai", "")
        if thai:
            schemes = generate_all(thai)
            card["romanization_paiboon"] = schemes.get("paiboon") or None
            card["romanization_rtgs"] = schemes.get("rtgs") or None
            card["romanization_ipa"] = schemes.get("ipa") or None
        else:
            card["romanization_paiboon"] = None
            card["romanization_rtgs"] = None
            card["romanization_ipa"] = None

        card["romanization_manual"] = None
        card["romanization"] = resolve_effective(card, prefs)


async def _generate_cards(raw_text: str) -> list:
    from json_repair import repair_json

    provider = get_provider(LLMTask.CARD_GENERATION)
    messages = build_card_generation_messages(raw_text)

    for attempt in range(2):
        response = await provider.complete(messages)
        raw_json = response.text.strip()

        if raw_json.startswith("```"):
            raw_json = raw_json.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        try:
            items = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            logger.warning(f"Card generation JSON error (attempt {attempt + 1}): {exc} — trying repair")
            logger.debug(f"Raw response (first 500 chars): {raw_json[:500]}")
            try:
                items = json.loads(repair_json(raw_json))
            except Exception as repair_exc:
                logger.warning(f"JSON repair also failed: {repair_exc}")
                continue

        if not isinstance(items, list):
            logger.warning(f"Card generation returned non-list (attempt {attempt + 1})")
            continue

        validated = []
        for item in items:
            try:
                validated.append(CardItem(**item).model_dump())
            except ValidationError:
                continue

        if validated:
            return validated

        logger.warning(f"Card generation produced 0 valid cards (attempt {attempt + 1})")

    return []


def _chunk_text(text: str, budget: int) -> list[str]:
    """Split text into chunks <= budget chars, splitting on blank lines / paragraphs."""
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 2  # +2 for the "\n\n" separator
        if current_len + para_len > budget and current_parts:
            chunks.append("\n\n".join(current_parts))
            current_parts = [para]
            current_len = para_len
        else:
            current_parts.append(para)
            current_len += para_len

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks or [text]


async def _generate_cards_chunked(raw_text: str, char_budget: int) -> list:
    """§7: chunk oversized text before generation; dedup results by thai field."""
    if len(raw_text) <= char_budget:
        return await _generate_cards(raw_text)

    chunks = _chunk_text(raw_text, char_budget)
    logger.info(f"Card generation: splitting {len(raw_text)} chars into {len(chunks)} chunks")

    all_cards: list[dict] = []
    seen_thai: set[str] = set()

    for i, chunk in enumerate(chunks):
        chunk_cards = await _generate_cards(chunk)
        for card in chunk_cards:
            thai = card.get("thai", "").strip()
            if thai and thai not in seen_thai:
                seen_thai.add(thai)
                all_cards.append(card)

    logger.info(f"Card generation: {len(all_cards)} unique cards from {len(chunks)} chunks")
    return all_cards
