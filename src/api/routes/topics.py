from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.db.services import topic_service
from src.db.models.tag import Tag, CardTag
from src.db.models.topic import Topic, CardTopic

router = APIRouter(prefix="/topics", tags=["topics"])


class MergeBody(BaseModel):
    target_id: int


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
    has_due: bool = Query(False, description="Only return topics with new or due cards"),
    db: AsyncSession = Depends(get_db),
):
    """List topics with card count, average FSRS difficulty, and due/new counts."""
    return await topic_service.list_topics(db, parent_id=parent_id, has_due=has_due)


@router.get("/duplicates")
async def topic_duplicates(db: AsyncSession = Depends(get_db)):
    """Return pairs of topics that are likely duplicates."""
    return await topic_service.find_potential_duplicates(db)


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


@router.get("/{topic_id}/summary")
async def get_topic_summary(topic_id: int, db: AsyncSession = Depends(get_db)):
    """Aggregated summary for the browse panel: counts, decks, card type breakdown."""
    summary = await topic_service.get_topic_summary(db, topic_id)
    if not summary:
        raise HTTPException(404, "Topic not found")
    return summary


@router.get("/{topic_id}/cards")
async def cards_in_topic(
    topic_id: int,
    card_type: Optional[str] = Query(None),
    fsrs_state: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Paginated cards in this topic (spanning all decks), with tags and topics."""
    topic = await topic_service.get_topic(db, topic_id)
    if not topic:
        raise HTTPException(404, "Topic not found")

    cards = await topic_service.get_cards_by_topic(
        db, topic_id, offset=offset, limit=limit, card_type=card_type, fsrs_state=fsrs_state
    )
    total = await topic_service.count_cards_by_topic(
        db, topic_id, card_type=card_type, fsrs_state=fsrs_state
    )

    card_ids = [c["id"] for c in cards]
    tags_map: dict[int, list] = {cid: [] for cid in card_ids}
    topics_map: dict[int, list] = {cid: [] for cid in card_ids}

    if card_ids:
        tag_rows = await db.execute(
            select(CardTag.card_id, Tag.id.label("tag_id"), Tag.name.label("tag_name"))
            .join(Tag, Tag.id == CardTag.tag_id)
            .where(CardTag.card_id.in_(card_ids))
        )
        for row in tag_rows:
            tags_map[row.card_id].append({"id": row.tag_id, "name": row.tag_name})

        topic_rows = await db.execute(
            select(CardTopic.card_id, Topic.id.label("topic_id"), Topic.name.label("topic_name"))
            .join(Topic, Topic.id == CardTopic.topic_id)
            .where(CardTopic.card_id.in_(card_ids))
        )
        for row in topic_rows:
            topics_map[row.card_id].append({"id": row.topic_id, "name": row.topic_name})

    items = []
    for card in cards:
        card["tags"] = tags_map[card["id"]]
        card["topics"] = topics_map[card["id"]]
        items.append(card)

    return {"items": items, "total": total, "offset": offset, "limit": limit}


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


@router.post("/{source_id}/merge")
async def merge_topics(
    source_id: int, payload: MergeBody, db: AsyncSession = Depends(get_db)
):
    """Merge source topic into target. Moves all cards, copies missing metadata, deletes source."""
    if source_id == payload.target_id:
        raise HTTPException(422, "source_id and target_id must be different")
    source = await topic_service.get_topic(db, source_id)
    if not source:
        raise HTTPException(404, f"Source topic {source_id} not found")
    target = await topic_service.get_topic(db, payload.target_id)
    if not target:
        raise HTTPException(404, f"Target topic {payload.target_id} not found")
    result = await topic_service.merge_topics(db, source_id, payload.target_id)
    await db.commit()
    return result
