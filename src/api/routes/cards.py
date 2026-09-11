import asyncio
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, not_, exists, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.db.services import card_service, tag_service, topic_service
from src.db.services import embedding_service
from src.db.services.card_service import count_cards_for_deck
from src.db.services.preferences_service import get_preferences
from src.db.models.card import Card
from src.db.models.card_flag import CardFlag
from src.db.models.tag import Tag, CardTag
from src.db.models.topic import Topic, CardTopic
from src.utils.romanization import generate_all, resolve_effective
from src.utils.card_overrides import apply_overrides, load_open_flag_targets, load_overrides, upsert_override
from src.utils.current_user import current_user

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


class TranslationResolve(BaseModel):
    action: str  # "keep" | "correct"
    english: Optional[str] = None


def _parse_json_field(value: Optional[str], default):
    if value is None:
        return default
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def _card_dict(
    card,
    include_analysis: bool = False,
    overrides: Optional[dict] = None,
    open_flags: Optional[list] = None,
):
    d = {
        "id": card.id,
        "deck_id": card.deck_id,
        "thai": card.thai,
        "romanization": card.romanization,
        "romanization_source": card.romanization_source,
        "romanization_paiboon": card.romanization_paiboon,
        "romanization_rtgs": card.romanization_rtgs,
        "romanization_ipa": card.romanization_ipa,
        "romanization_manual": card.romanization_manual,
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
        "is_compound": card.is_compound,
        "compound_breakdown": _parse_json_field(card.compound_breakdown, None),
        "translation_status": card.translation_status,
        "translation_candidates": _parse_json_field(card.translation_candidates, None),
    }
    if include_analysis:
        d["script_analysis"] = _parse_json_field(card.script_analysis, [])
    d = apply_overrides(d, overrides or {})
    d["open_flag_targets"] = open_flags or []
    d["has_open_flags"] = bool(open_flags)
    return d


@router.get("/decks/{deck_id}/cards")
async def list_cards(
    deck_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    tagged: Optional[bool] = Query(None, description="true=tagged only, false=untagged only"),
    translation_status: Optional[str] = Query(None, description="Filter by translation_status, e.g. 'flagged'"),
    needs_attention: bool = Query(
        False, description="Flagged translation status OR an open user flag of any target"
    ),
    include_analysis: bool = Query(False, description="Include verbose per-syllable script_analysis in response"),
    db: AsyncSession = Depends(get_db),
):
    if tagged is False or translation_status is not None or needs_attention:
        stmt = select(Card).where(Card.deck_id == deck_id)
        if tagged is False:
            stmt = stmt.where(not_(exists(select(CardTag.card_id).where(CardTag.card_id == Card.id))))
        if translation_status is not None:
            stmt = stmt.where(Card.translation_status == translation_status)
        if needs_attention:
            stmt = stmt.where(
                or_(
                    Card.translation_status == "flagged",
                    exists(
                        select(CardFlag.id).where(
                            CardFlag.card_id == Card.id,
                            CardFlag.user_id == current_user(),
                            CardFlag.status == "open",
                        )
                    ),
                )
            )
        stmt = stmt.order_by(Card.created_at.desc()).offset(offset).limit(limit)
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

    user_id = current_user()
    overrides_map = await load_overrides(db, card_ids, user_id)
    flags_map = await load_open_flag_targets(db, card_ids, user_id)

    items = []
    for card in cards:
        d = _card_dict(
            card,
            include_analysis=include_analysis,
            overrides=overrides_map.get(card.id),
            open_flags=flags_map.get(card.id),
        )
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

    user_id = current_user()
    overrides_map = await load_overrides(db, [card_id], user_id)
    flags_map = await load_open_flag_targets(db, [card_id], user_id)

    d = _card_dict(
        card,
        include_analysis=True,
        overrides=overrides_map.get(card_id),
        open_flags=flags_map.get(card_id),
    )
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
    prefs = await get_preferences(db)
    schemes = await asyncio.to_thread(generate_all, payload.thai)
    romanization_manual = payload.romanization or None
    effective = resolve_effective(
        {
            "romanization_source": None,
            "romanization_paiboon": schemes.get("paiboon") or None,
            "romanization_rtgs": schemes.get("rtgs") or None,
            "romanization_ipa": schemes.get("ipa") or None,
            "romanization_manual": romanization_manual,
        },
        prefs,
    )
    card = await card_service.create_card(
        db,
        deck_id=deck_id,
        thai=payload.thai,
        english=payload.english,
        romanization=effective,
        romanization_paiboon=schemes.get("paiboon") or None,
        romanization_rtgs=schemes.get("rtgs") or None,
        romanization_ipa=schemes.get("ipa") or None,
        romanization_manual=romanization_manual,
        example_thai=payload.example_thai,
        example_english=payload.example_english,
        card_type=payload.card_type,
    )
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

    update_kwargs = payload.model_dump(exclude_none=True)

    # User-provided 'romanization' becomes the manual override
    user_romanization = update_kwargs.pop("romanization", None)
    if user_romanization is not None:
        update_kwargs["romanization_manual"] = user_romanization

    thai_changed = "thai" in update_kwargs
    romanization_touched = user_romanization is not None

    if thai_changed or romanization_touched:
        current_thai = update_kwargs.get("thai", card.thai)
        prefs = await get_preferences(db)

        if thai_changed:
            schemes = await asyncio.to_thread(generate_all, current_thai)
            update_kwargs["romanization_paiboon"] = schemes.get("paiboon") or None
            update_kwargs["romanization_rtgs"] = schemes.get("rtgs") or None
            update_kwargs["romanization_ipa"] = schemes.get("ipa") or None

        values = {
            "romanization_source": card.romanization_source,
            "romanization_paiboon": update_kwargs.get("romanization_paiboon", card.romanization_paiboon),
            "romanization_rtgs": update_kwargs.get("romanization_rtgs", card.romanization_rtgs),
            "romanization_ipa": update_kwargs.get("romanization_ipa", card.romanization_ipa),
            "romanization_manual": update_kwargs.get("romanization_manual", card.romanization_manual),
        }
        update_kwargs["romanization"] = resolve_effective(values, prefs)

    card = await card_service.update_card(db, card, **update_kwargs)
    await db.commit()
    return _card_dict(card, include_analysis=include_analysis)


@router.post("/cards/{card_id}/resolve-translation")
async def resolve_translation(
    card_id: int,
    payload: TranslationResolve,
    db: AsyncSession = Depends(get_db),
):
    """User's verdict on a flagged translation: keep the material value, or
    correct it. 'correct' writes a translation override, not `cards.english`
    — the material value stays the source-of-truth row; only this user's
    display layer changes. See src/utils/card_overrides.py."""
    card = await card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    if payload.action == "keep":
        card = await card_service.update_card(
            db, card, translation_status="confirmed", translation_candidates=None
        )
    elif payload.action == "correct":
        if not payload.english or not payload.english.strip():
            raise HTTPException(422, "english is required when action is 'correct'")
        await upsert_override(
            db, current_user(), card_id, "translation",
            {"english": payload.english, "from_candidate": False},
        )
        card = await card_service.update_card(
            db, card, translation_status="confirmed", translation_candidates=None
        )
    else:
        raise HTTPException(422, "action must be 'keep' or 'correct'")

    await db.commit()
    overrides_map = await load_overrides(db, [card_id], current_user())
    return _card_dict(card, overrides=overrides_map.get(card_id))


@router.post("/cards/{card_id}/enrich-breakdown")
async def enrich_breakdown(card_id: int, db: AsyncSession = Depends(get_db)):
    """User-triggered: fill compound-gloss gaps left by the deterministic
    ladder via a single Haiku call. No-op (and no LLM call) when the card
    isn't a surfaced compound or every part already has a gloss."""
    from src.db.services import compound_llm_service

    card = await card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    try:
        result = await compound_llm_service.enrich_breakdown(db, card_id)
    except Exception as exc:
        raise HTTPException(502, "Compound gloss enrichment failed") from exc

    if result.get("status") == "enriched" and result.get("persisted"):
        await db.commit()
        card = await card_service.get_card(db, card_id)

    overrides_map = await load_overrides(db, [card_id], current_user())
    return {**result, "card": _card_dict(card, overrides=overrides_map.get(card_id))}


@router.post("/cards/{card_id}/verify-translation")
async def verify_translation(card_id: int, db: AsyncSession = Depends(get_db)):
    """User-triggered: get a second opinion on a flagged translation via a
    single Haiku call. Advisory only — never changes translation_status or
    english. No-op (and no LLM call) unless the card is currently flagged."""
    from src.db.services import translation_verify_service

    card = await card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    try:
        result = await translation_verify_service.verify_translation(db, card_id)
    except Exception as exc:
        raise HTTPException(502, "Translation verification failed") from exc

    return result


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
