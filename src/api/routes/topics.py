from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.db.services import topic_service

router = APIRouter(prefix="/topics", tags=["topics"])


class TopicCreate(BaseModel):
    name: str
    description: Optional[str] = None
    parent_id: Optional[int] = None
    sort_order: int = 0


class TopicUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[int] = None
    sort_order: Optional[int] = None


class BulkAssign(BaseModel):
    card_ids: list[int]


@router.get("")
async def list_topics(
    parent_id: Optional[int] = Query(None, description="Filter to subtopics of this topic"),
    db: AsyncSession = Depends(get_db),
):
    """List topics with card count and average FSRS difficulty."""
    return await topic_service.list_topics(db, parent_id=parent_id)


@router.get("/tree")
async def topic_tree(db: AsyncSession = Depends(get_db)):
    """Return the full topic hierarchy as a nested tree."""
    return await topic_service.get_topic_tree(db)


@router.get("/gap-report")
async def gap_report(db: AsyncSession = Depends(get_db)):
    """
    Comprehensive coverage gap report:
    - Topics with fewer than 5 cards
    - Cards not assigned to any topic, grouped by deck
    - Card type distribution per topic
    - Average FSRS difficulty per topic
    - Topics where no card has ever been reviewed
    """
    return await topic_service.get_gap_report(db)


@router.get("/{topic_id}")
async def get_topic(topic_id: int, db: AsyncSession = Depends(get_db)):
    topic = await topic_service.get_topic(db, topic_id)
    if not topic:
        raise HTTPException(404, "Topic not found")
    return {
        "id": topic.id,
        "name": topic.name,
        "description": topic.description,
        "parent_id": topic.parent_id,
        "sort_order": topic.sort_order,
        "created_at": topic.created_at.isoformat(),
    }


@router.get("/{topic_id}/cards")
async def cards_in_topic(
    topic_id: int,
    card_type: Optional[str] = Query(None),
    fsrs_state: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Paginated cards in this topic (spanning all decks)."""
    topic = await topic_service.get_topic(db, topic_id)
    if not topic:
        raise HTTPException(404, "Topic not found")
    return await topic_service.get_cards_by_topic(
        db, topic_id, offset=offset, limit=limit, card_type=card_type, fsrs_state=fsrs_state
    )


@router.post("", status_code=201)
async def create_topic(payload: TopicCreate, db: AsyncSession = Depends(get_db)):
    topic = await topic_service.create_topic(
        db,
        name=payload.name,
        description=payload.description,
        parent_id=payload.parent_id,
        sort_order=payload.sort_order,
    )
    await db.commit()
    return {"id": topic.id, "name": topic.name, "parent_id": topic.parent_id}


@router.patch("/{topic_id}")
async def update_topic(
    topic_id: int, payload: TopicUpdate, db: AsyncSession = Depends(get_db)
):
    topic = await topic_service.get_topic(db, topic_id)
    if not topic:
        raise HTTPException(404, "Topic not found")
    topic = await topic_service.update_topic(db, topic, **payload.model_dump(exclude_none=True))
    await db.commit()
    return {"id": topic.id, "name": topic.name, "parent_id": topic.parent_id, "sort_order": topic.sort_order}


@router.delete("/{topic_id}", status_code=204)
async def delete_topic(topic_id: int, db: AsyncSession = Depends(get_db)):
    topic = await topic_service.get_topic(db, topic_id)
    if not topic:
        raise HTTPException(404, "Topic not found")
    await topic_service.delete_topic(db, topic)
    await db.commit()


@router.post("/{topic_id}/cards", status_code=201)
async def assign_cards(
    topic_id: int, payload: BulkAssign, db: AsyncSession = Depends(get_db)
):
    """Bulk-assign cards to this topic. Already-assigned cards are silently skipped."""
    topic = await topic_service.get_topic(db, topic_id)
    if not topic:
        raise HTTPException(404, "Topic not found")
    count = await topic_service.assign_cards(db, topic_id, payload.card_ids)
    await db.commit()
    return {"assigned": count}


@router.delete("/{topic_id}/cards/{card_id}", status_code=204)
async def remove_card_from_topic(
    topic_id: int, card_id: int, db: AsyncSession = Depends(get_db)
):
    """Remove a card from a topic."""
    topic = await topic_service.get_topic(db, topic_id)
    if not topic:
        raise HTTPException(404, "Topic not found")
    removed = await topic_service.remove_card(db, topic_id, card_id)
    if not removed:
        raise HTTPException(404, "Card is not assigned to this topic")
    await db.commit()
