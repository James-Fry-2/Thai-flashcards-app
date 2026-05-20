"""
Background upload processing pipeline.
Called via FastAPI BackgroundTasks; OCR runs in asyncio.to_thread.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Optional
from loguru import logger
from sqlalchemy import select

from src.config.settings import get_settings
from src.db.database import get_session_factory
from src.db.models.upload import Upload
from src.db.models.card import Card
from src.ocr.pipeline import run_ocr_pipeline
from src.utils.file_parser import prepare_file_for_ocr
from src.llm.registry import get_provider, LLMTask
from src.llm.prompts.card_generation import build_card_generation_messages
from src.db.services.card_service import bulk_create_cards, create_card

from pydantic import BaseModel, ValidationError


class CardItem(BaseModel):
    thai: str
    romanization: Optional[str] = None
    english: str
    example_thai: Optional[str] = None
    example_english: Optional[str] = None
    card_type: str = "vocab"


async def run_upload_pipeline(upload_id: int) -> None:
    """
    Full async pipeline: read file → OCR → LLM card generation → insert cards.
    Runs as a FastAPI BackgroundTask.
    """
    settings = get_settings()
    factory = get_session_factory()

    async with factory() as db:
        upload = await db.get(Upload, upload_id)
        if not upload:
            logger.error(f"Upload {upload_id} not found")
            return

        try:
            await _process(db, upload, settings)
        except Exception as exc:
            logger.exception(f"Upload {upload_id} failed: {exc}")
            upload.status = "failed"
            upload.error_message = str(exc)
            await db.commit()


async def _process(db, upload: Upload, settings) -> None:
    upload.status = "processing"
    await db.commit()

    # 1. Load file from disk
    file_path = Path(settings.media_dir) / "uploads" / str(upload.id) / upload.filename
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    file_bytes = file_path.read_bytes()

    # 2. Convert to images and OCR each page
    image_pages = await asyncio.to_thread(prepare_file_for_ocr, file_bytes, upload.filename)
    all_text_parts = []
    last_engine = "claude_vision"
    last_confidence = 1.0

    for image_bytes, media_type in image_pages:
        result = await run_ocr_pipeline(image_bytes, media_type)
        all_text_parts.append(result.text)
        last_engine = result.engine_used
        last_confidence = result.confidence

    raw_text = "\n\n".join(filter(None, all_text_parts))
    upload.raw_text = raw_text
    upload.ocr_engine_used = last_engine
    upload.ocr_confidence = last_confidence
    await db.commit()

    if not raw_text.strip():
        upload.status = "done"
        upload.cards_created = 0
        await db.commit()
        return

    # 3. Hash OCR text — skip LLM if we've seen this exact content before
    text_hash = hashlib.sha256(raw_text.encode()).hexdigest()
    upload.text_hash = text_hash

    prior = await db.scalar(
        select(Upload).where(
            Upload.text_hash == text_hash,
            Upload.cards_created > 0,
            Upload.id != upload.id,
        )
    )

    if prior and upload.deck_id:
        # Clone cards from the prior upload instead of calling the LLM
        logger.info(f"Upload {upload.id}: duplicate of upload {prior.id}, cloning {prior.cards_created} cards")
        source_cards = await db.scalars(
            select(Card).where(Card.source_upload_id == prior.id)
        )
        cloned = []
        for card in source_cards:
            cloned.append(await create_card(
                db,
                deck_id=upload.deck_id,
                thai=card.thai,
                english=card.english,
                romanization=card.romanization,
                example_thai=card.example_thai,
                example_english=card.example_english,
                card_type=card.card_type,
                source_upload_id=upload.id,
            ))
        upload.cards_created = len(cloned)
        upload.status = "done"
        await db.commit()
        return

    # 4. Generate cards via LLM
    cards_data = await _generate_cards(raw_text)

    # 4b. Fill missing romanization using library-based Paiboon+ generator
    await asyncio.to_thread(_fill_paiboon, cards_data)

    # 5. Insert cards into the deck
    if upload.deck_id and cards_data:
        created = await bulk_create_cards(
            db,
            deck_id=upload.deck_id,
            cards_data=cards_data,
            source_upload_id=upload.id,
        )
        upload.cards_created = len(created)
    else:
        upload.cards_created = 0

    upload.status = "done"
    await db.commit()
    logger.info(f"Upload {upload.id}: {upload.cards_created} cards created via {last_engine}")


def _fill_paiboon(cards_data: list) -> None:
    """
    For each card that has no romanization after LLM extraction, generate
    Paiboon+ via the PyThaiNLP-based library converter.
    Runs synchronously (called inside asyncio.to_thread).
    """
    from src.utils.paiboon import thai_to_paiboon

    for card in cards_data:
        if not card.get("romanization"):
            result = thai_to_paiboon(card.get("thai", ""))
            card["romanization"] = result or None


async def _generate_cards(raw_text: str) -> list:
    from json_repair import repair_json

    provider = get_provider(LLMTask.CARD_GENERATION)
    messages = build_card_generation_messages(raw_text)

    for attempt in range(2):
        response = await provider.complete(messages)
        raw_json = response.text.strip()

        # Strip accidental markdown fences
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
