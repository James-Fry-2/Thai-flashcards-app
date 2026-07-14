from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.db.services import search_service, topic_service
from src.db.models.topic import Topic

router = APIRouter(prefix="/search", tags=["search"])


class SaveAsTopicRequest(BaseModel):
    name: str
    card_ids: list[int]
    description: Optional[str] = None


@router.get("/study")
async def study_search(
    q: str = Query(..., description="Search query"),
    deck_id: Optional[int] = Query(None),
    card_type: Optional[str] = Query(None),
    limit_cards: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Hybrid study-oriented search: returns matching groupings (topics/tags), an ad-hoc card set, and a card browse list."""
    return await search_service.study_search(
        db,
        query=q,
        limit_cards=limit_cards,
        deck_id=deck_id,
        card_type=card_type,
    )


@router.post("/save-as-topic", status_code=201)
async def save_as_topic(
    payload: SaveAsTopicRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create (or reuse) a topic by name and assign all provided card IDs to it.
    Uses get_or_create_topic so it integrates with the existing dedup/merge tooling."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "name must not be empty")
    if not payload.card_ids:
        raise HTTPException(422, "card_ids must not be empty")
    if len(payload.card_ids) > 500:
        raise HTTPException(422, "card_ids must contain at most 500 items")

    # Pre-check: does a topic with this name already exist?
    existing = await db.scalar(
        select(Topic).where(func.lower(Topic.name) == func.lower(name))
    )
    already_existed = existing is not None

    # get_or_create_topic: looks up by case-insensitive name, creates if missing
    topic = await topic_service.get_or_create_topic(db, name)

    # If caller supplied a description and the topic has none, fill it in
    if payload.description and not topic.description:
        await topic_service.update_topic(db, topic, description=payload.description)

    cards_assigned = await topic_service.assign_cards(db, topic.id, payload.card_ids)
    await db.commit()

    return {
        "topic_id": topic.id,
        "name": topic.name,
        "created": not already_existed,
        "cards_assigned": cards_assigned,
    }
