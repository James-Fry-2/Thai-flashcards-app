import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, not_, exists
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.db.services import card_service, tag_service, topic_service
from src.db.services import embedding_service
from src.db.services.card_service import count_cards_for_deck
from src.db.models.card import Card
from src.db.models.tag import Tag, CardTag
from src.db.models.topic import Topic, CardTopic

router = APIRouter(tags=["cards"])


class CardCreate(BaseModel):
    thai: str
    english: str
    romanization: Optional[str] = None
    example_thai: Optional[str] = None
    example_english: Optional[str] = None
    card_type: str = "vocab"


class CardUpdate(BaseModel):
    thai: Optional[str] = None
    english: Optional[str] = None
    romanization: Optional[str] = None
    example_thai: Optional[str] = None
    example_english: Optional[str] = None
    notes: Optional[str] = None
    card_type: Optional[str] = None


class CardTagAdd(BaseModel):
    tag_name: Optional[str] = None
    tag_id: Optional[int] = None


class CardTopicAdd(BaseModel):
    topic_name: Optional[str] = None
    topic_id: Optional[int] = None


def _parse_json_field(value: Optional[str], default):
    if value is None:
        return default
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def _card_dict(card, include_analysis: bool = False):
    d = {
        "id": card.id,
        "deck_id": card.deck_id,
        "thai": card.thai,
        "romanization": card.romanization,
        "english": card.english,
        "example_thai": card.example_thai,
        "example_english": card.example_english,
        "notes": card.notes,
        "card_type": card.card_type,
        "created_at": card.created_at.isoformat(),
        "syllable_count": card.syllable_count,
        "tone_pattern": _parse_json_field(card.tone_pattern, []),
        "consonant_classes": _parse_json_field(card.consonant_classes, []),
        "has_cluster": card.has_cluster,
        "has_rare_consonant": card.has_rare_consonant,
        "has_silent_mark": card.has_silent_mark,
    }
    if include_analysis:
        d["script_analysis"] = _parse_json_field(card.script_analysis, [])
    return d


@router.get("/decks/{deck_id}/cards")
async def list_cards(
    deck_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    tagged: Optional[bool] = Query(None, description="true=tagged only, false=untagged only"),
    include_analysis: bool = Query(False, description="Include verbose per-syllable script_analysis in response"),
    db: AsyncSession = Depends(get_db),
):
    if tagged is False:
        stmt = (
            select(Card)
            .where(Card.deck_id == deck_id)
            .where(not_(exists(select(CardTag.card_id).where(CardTag.card_id == Card.id))))
            .order_by(Card.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(stmt)
        cards = list(result.scalars().all())
    else:
        cards = await card_service.get_cards_for_deck(db, deck_id, offset=offset, limit=limit)

    card_ids = [c.id for c in cards]
    tags_map: dict[int, list[dict]] = {cid: [] for cid in card_ids}
    topics_map: dict[int, list[dict]] = {cid: [] for cid in card_ids}

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
        d = _card_dict(card, include_analysis=include_analysis)
        d["tags"] = tags_map[card.id]
        d["topics"] = topics_map[card.id]
        items.append(d)

    total = await count_cards_for_deck(db, deck_id)
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.get("/cards/{card_id}")
async def get_card_detail(card_id: int, db: AsyncSession = Depends(get_db)):
    """Single card with tags, topics, script analysis, and links."""
    from src.db.services import link_service

    card = await card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    tag_rows = await db.execute(
        select(Tag.id, Tag.name)
        .join(CardTag, CardTag.tag_id == Tag.id)
        .where(CardTag.card_id == card_id)
    )
    tags = [{"id": row.id, "name": row.name} for row in tag_rows]

    topic_rows = await db.execute(
        select(Topic.id, Topic.name)
        .join(CardTopic, CardTopic.topic_id == Topic.id)
        .where(CardTopic.card_id == card_id)
    )
    topics = [{"id": row.id, "name": row.name} for row in topic_rows]

    links = await link_service.get_card_links(db, card_id)

    d = _card_dict(card, include_analysis=True)
    d["tags"] = tags
    d["topics"] = topics
    d["links"] = links
    return d


@router.post("/decks/{deck_id}/cards", status_code=201)
async def create_card(
    deck_id: int,
    payload: CardCreate,
    include_analysis: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    card = await card_service.create_card(db, deck_id=deck_id, **payload.model_dump())
    await db.commit()
    return _card_dict(card, include_analysis=include_analysis)


@router.patch("/cards/{card_id}")
async def update_card(
    card_id: int,
    payload: CardUpdate,
    include_analysis: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    card = await card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    card = await card_service.update_card(db, card, **payload.model_dump(exclude_none=True))
    await db.commit()
    return _card_dict(card, include_analysis=include_analysis)


@router.delete("/cards/{card_id}", status_code=204)
async def delete_card(card_id: int, db: AsyncSession = Depends(get_db)):
    card = await card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    await card_service.delete_card(db, card)
    await db.commit()


@router.post("/cards/{card_id}/tags", status_code=201)
async def add_tag_to_card(
    card_id: int, payload: CardTagAdd, db: AsyncSession = Depends(get_db)
):
    card = await card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    if payload.tag_id is not None:
        tag = await tag_service.get_tag(db, payload.tag_id)
        if not tag:
            raise HTTPException(404, "Tag not found")
    elif payload.tag_name is not None:
        tag = await card_service.get_or_create_tag(db, payload.tag_name)
    else:
        raise HTTPException(422, "Either tag_name or tag_id must be provided")

    existing = await db.scalar(
        select(CardTag).where(CardTag.card_id == card_id, CardTag.tag_id == tag.id)
    )
    if not existing:
        db.add(CardTag(card_id=card_id, tag_id=tag.id))
        await db.flush()
    await db.commit()
    return {"tag_id": tag.id, "tag_name": tag.name}


@router.delete("/cards/{card_id}/tags/{tag_id}", status_code=204)
async def remove_tag_from_card(
    card_id: int, tag_id: int, db: AsyncSession = Depends(get_db)
):
    card = await card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    tag = await tag_service.get_tag(db, tag_id)
    if not tag:
        raise HTTPException(404, "Tag not found")
    ct = await db.scalar(
        select(CardTag).where(CardTag.card_id == card_id, CardTag.tag_id == tag_id)
    )
    if ct:
        await db.delete(ct)
        await db.flush()
    await db.commit()


@router.post("/cards/{card_id}/topics", status_code=201)
async def add_topic_to_card(
    card_id: int, payload: CardTopicAdd, db: AsyncSession = Depends(get_db)
):
    card = await card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    if payload.topic_id is not None:
        topic = await topic_service.get_topic(db, payload.topic_id)
        if not topic:
            raise HTTPException(404, "Topic not found")
    elif payload.topic_name is not None:
        topic = await topic_service.get_or_create_topic(db, payload.topic_name)
    else:
        raise HTTPException(422, "Either topic_name or topic_id must be provided")

    existing = await db.scalar(
        select(CardTopic).where(
            CardTopic.card_id == card_id, CardTopic.topic_id == topic.id
        )
    )
    if not existing:
        db.add(CardTopic(card_id=card_id, topic_id=topic.id))
        await db.flush()
    await db.commit()
    return {"topic_id": topic.id, "topic_name": topic.name}


@router.get("/cards/{card_id}/similar")
async def get_similar_cards(
    card_id: int,
    limit: int = Query(20, ge=1, le=50),
    min_similarity: float = Query(0.5, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
):
    """Return cards most similar to the given card by embedding similarity."""
    card = await card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    return await embedding_service.find_similar_cards(db, card_id, limit=limit, min_similarity=min_similarity)


@router.delete("/cards/{card_id}/topics/{topic_id}", status_code=204)
async def remove_topic_from_card(
    card_id: int, topic_id: int, db: AsyncSession = Depends(get_db)
):
    card = await card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    topic = await topic_service.get_topic(db, topic_id)
    if not topic:
        raise HTTPException(404, "Topic not found")
    await topic_service.remove_card(db, topic_id, card_id)
    await db.commit()
