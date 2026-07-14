import json
from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.card import Card
from src.db.models.tag import CardTag
from src.db.models.topic import Topic, CardTopic
from src.db.services.card_service import get_or_create_tag, add_tag_to_card
from src.db.services.topic_service import get_or_create_topic, assign_cards

BATCH_SIZE = 25


async def get_existing_topic_names(db: AsyncSession, limit: int = 50) -> list[str]:
    """Return up to `limit` existing topic names, most-used first."""
    stmt = (
        select(Topic.name, func.count(CardTopic.card_id).label("usage"))
        .outerjoin(CardTopic, CardTopic.topic_id == Topic.id)
        .group_by(Topic.id)
        .order_by(func.count(CardTopic.card_id).desc(), Topic.name)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [row.name for row in result]


async def tag_cards(db: AsyncSession, card_ids: list[int]) -> dict:
    """
    Fetch cards, call the LLM tagging pass, and persist topic + tags.
    Batches in groups of BATCH_SIZE. Returns an aggregated summary dict.
    """
    summary = {"tagged": 0, "failed": [], "topics_created": [], "tags_created": []}

    for i in range(0, len(card_ids), BATCH_SIZE):
        batch_ids = card_ids[i : i + BATCH_SIZE]
        batch_summary = await _tag_batch(db, batch_ids)
        summary["tagged"] += batch_summary["tagged"]
        summary["failed"].extend(batch_summary["failed"])
        summary["topics_created"].extend(batch_summary["topics_created"])
        summary["tags_created"].extend(batch_summary["tags_created"])

    # Deduplicate newly-created name lists across batches
    summary["topics_created"] = list(dict.fromkeys(summary["topics_created"]))
    summary["tags_created"] = list(dict.fromkeys(summary["tags_created"]))
    return summary


async def _tag_batch(db: AsyncSession, card_ids: list[int]) -> dict:
    from json_repair import repair_json
    from src.llm.registry import get_provider, LLMTask
    from src.llm.prompts.card_tagging import build_card_tagging_messages

    # Fetch cards
    result = await db.execute(select(Card).where(Card.id.in_(card_ids)))
    cards = {c.id: c for c in result.scalars().all()}

    card_dicts = [
        {
            "id": c.id,
            "thai": c.thai,
            "english": c.english,
            **({"example_thai": c.example_thai} if c.example_thai else {}),
        }
        for c in cards.values()
    ]

    existing_topics = await get_existing_topic_names(db)

    provider = get_provider(LLMTask.CARD_TAGGING)
    messages = build_card_tagging_messages(card_dicts, existing_topics)

    response = await provider.complete(messages)
    raw_json = response.text.strip()

    if raw_json.startswith("```"):
        raw_json = raw_json.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        items = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        logger.warning(f"Card tagging JSON error: {exc} — trying repair")
        try:
            items = json.loads(repair_json(raw_json))
        except Exception as repair_exc:
            logger.warning(f"Card tagging JSON repair failed: {repair_exc}")
            return {"tagged": 0, "failed": list(card_ids), "topics_created": [], "tags_created": []}

    if not isinstance(items, list):
        logger.warning("Card tagging returned non-list response")
        return {"tagged": 0, "failed": list(card_ids), "topics_created": [], "tags_created": []}

    # Snapshot existing names to detect newly created ones
    existing_topic_names_lower = {n.lower() for n in existing_topics}
    from src.db.models.tag import Tag
    tag_name_result = await db.execute(select(Tag.name))
    existing_tag_names_lower = {row[0].lower() for row in tag_name_result}

    tagged = 0
    failed = []
    topics_created: list[str] = []
    tags_created: list[str] = []

    responded_ids: set[int] = set()

    for item in items:
        card_id = item.get("id")
        if not isinstance(card_id, int) or card_id not in cards:
            continue
        responded_ids.add(card_id)

        topic_name = item.get("topic", "")
        if not isinstance(topic_name, str) or not topic_name.strip():
            failed.append(card_id)
            continue

        raw_tags = item.get("tags", [])
        if not isinstance(raw_tags, list):
            raw_tags = []
        tag_names = [t for t in raw_tags if isinstance(t, str) and t.strip()][:5]

        # Apply topic
        topic = await get_or_create_topic(db, topic_name.strip())
        if topic.name.lower() not in existing_topic_names_lower:
            topics_created.append(topic.name)
            existing_topic_names_lower.add(topic.name.lower())
        await assign_cards(db, topic.id, [card_id])

        # Apply tags
        for tag_name in tag_names:
            tag_name = tag_name.strip()
            if not tag_name:
                continue
            is_new = tag_name.lower() not in existing_tag_names_lower
            await add_tag_to_card(db, card_id, tag_name)
            if is_new:
                tags_created.append(tag_name.lower())
                existing_tag_names_lower.add(tag_name.lower())

        tagged += 1

    # Cards the LLM didn't return an entry for
    for card_id in card_ids:
        if card_id not in responded_ids:
            failed.append(card_id)

    return {
        "tagged": tagged,
        "failed": failed,
        "topics_created": topics_created,
        "tags_created": tags_created,
    }


async def copy_tags_and_topic(
    db: AsyncSession, source_card_id: int, target_card_id: int
) -> None:
    """Copy all tags and topic assignments from source_card to target_card."""
    # Copy tags
    tag_result = await db.execute(
        select(CardTag).where(CardTag.card_id == source_card_id)
    )
    for ct in tag_result.scalars().all():
        existing = await db.scalar(
            select(CardTag).where(
                CardTag.card_id == target_card_id, CardTag.tag_id == ct.tag_id
            )
        )
        if not existing:
            db.add(CardTag(card_id=target_card_id, tag_id=ct.tag_id))

    # Copy topics
    topic_result = await db.execute(
        select(CardTopic).where(CardTopic.card_id == source_card_id)
    )
    for ct in topic_result.scalars().all():
        existing = await db.scalar(
            select(CardTopic).where(
                CardTopic.card_id == target_card_id, CardTopic.topic_id == ct.topic_id
            )
        )
        if not existing:
            db.add(CardTopic(card_id=target_card_id, topic_id=ct.topic_id))

    await db.flush()
