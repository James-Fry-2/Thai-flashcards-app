"""Read & mine mode: read uploaded pages, look up words, add cards, mark known."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.db.services import reading_service
from src.utils.current_user import current_user
from src.utils.text_integrity import find_invalid_chars, normalise_text

router = APIRouter(prefix="/reading", tags=["reading"])


def _clean_thai(value: str) -> str:
    thai, _ = normalise_text(value.strip())
    if not thai or not reading_service.is_thai_word(thai):
        raise HTTPException(422, "thai must contain Thai text")
    bad = find_invalid_chars(thai)
    if bad:
        raise HTTPException(422, f"thai contains invalid character {bad[0][1]} at {bad[0][0]}")
    return thai


@router.get("/uploads")
async def list_readable(db: AsyncSession = Depends(get_db)):
    """Uploads that have readable page text, with how much of each you know."""
    return await reading_service.list_readable(db, current_user())


@router.get("/uploads/{upload_id}/pages/{page_index}")
async def get_page(upload_id: int, page_index: int, db: AsyncSession = Depends(get_db)):
    page = await reading_service.get_page(db, current_user(), upload_id, page_index)
    if page is None:
        raise HTTPException(404, "Page not found")
    return page


@router.get("/uploads/{upload_id}/first-page")
async def first_page(upload_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    from src.db.models.upload_page import UploadPage

    idx = await db.scalar(
        select(UploadPage.page_index)
        .where(UploadPage.upload_id == upload_id, UploadPage.text.isnot(None))
        .order_by(UploadPage.page_index)
        .limit(1)
    )
    if idx is None:
        raise HTTPException(404, "No readable pages")
    return {"page_index": idx}


@router.get("/lookup")
async def lookup(thai: str = Query(..., min_length=1), db: AsyncSession = Depends(get_db)):
    result = await reading_service.lookup_word(db, current_user(), _clean_thai(thai))
    await db.commit()  # get_preferences may create the row
    return result


class AddCardRequest(BaseModel):
    thai: str
    english: str = Field(..., min_length=1)
    upload_id: Optional[int] = None
    example_thai: Optional[str] = None


@router.post("/cards", status_code=201)
async def add_card(payload: AddCardRequest, db: AsyncSession = Depends(get_db)):
    thai = _clean_thai(payload.thai)
    example = None
    if payload.example_thai and payload.example_thai.strip() and payload.example_thai.strip() != thai:
        example, _ = normalise_text(payload.example_thai.strip())
        if find_invalid_chars(example):
            example = None
    card, created = await reading_service.add_card(
        db, thai, payload.english.strip(), payload.upload_id, example
    )
    await db.commit()
    return {"card_id": card.id, "deck_id": card.deck_id, "created": created}


class KnownRequest(BaseModel):
    thai: str
    known: bool = True


@router.post("/known")
async def mark_known(payload: KnownRequest, db: AsyncSession = Depends(get_db)):
    thai = _clean_thai(payload.thai)
    await reading_service.mark_known(db, current_user(), thai, payload.known)
    await db.commit()
    return {"thai": thai, "known": payload.known}


# ---------------------------------------------------------------------------
# Generated texts (dialogues / example sentences)
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    kind: str = Field(..., pattern="^(dialogue|sentences)$")
    topic_id: Optional[int] = None
    upload_id: Optional[int] = None


@router.get("/sources")
async def list_sources(db: AsyncSession = Depends(get_db)):
    """Topics and chapters with enough cards to generate a text from."""
    from src.db.services import reading_text_service
    return await reading_text_service.list_sources(db)


@router.post("/texts", status_code=201)
async def generate_text(payload: GenerateRequest, db: AsyncSession = Depends(get_db)):
    """Write a dialogue or example sentences with Claude, then check them.

    Makes two model calls, so it can take up to a minute or so.
    """
    from src.db.services import reading_text_service
    from src.llm.base import LLMRefusal

    if (payload.topic_id is None) == (payload.upload_id is None):
        raise HTTPException(422, "Provide exactly one of topic_id or upload_id")
    scope, scope_id = ("topic", payload.topic_id) if payload.topic_id is not None else ("upload", payload.upload_id)
    try:
        text = await reading_text_service.generate(db, current_user(), payload.kind, scope, scope_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except reading_text_service.GenerationError as exc:
        raise HTTPException(422, str(exc))
    except LLMRefusal:
        raise HTTPException(502, "Claude declined to write this text. Try a different topic.")
    await db.commit()
    return {"id": text.id}


@router.get("/texts")
async def list_texts(db: AsyncSession = Depends(get_db)):
    from src.db.services import reading_text_service
    return await reading_text_service.list_texts(db, current_user())


@router.get("/texts/{text_id}")
async def get_text(text_id: int, db: AsyncSession = Depends(get_db)):
    from src.db.services import reading_text_service
    text = await reading_text_service.get_text(db, current_user(), text_id)
    if text is None:
        raise HTTPException(404, "Text not found")
    await db.commit()  # may have backfilled romanization / created preferences
    return text


@router.delete("/texts/{text_id}", status_code=204)
async def delete_text(text_id: int, db: AsyncSession = Depends(get_db)):
    from src.db.services import reading_text_service
    if not await reading_text_service.delete_text(db, current_user(), text_id):
        raise HTTPException(404, "Text not found")
    await db.commit()
