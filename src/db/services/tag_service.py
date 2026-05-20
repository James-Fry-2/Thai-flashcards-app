from typing import Optional
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.tag import Tag, CardTag
from src.db.models.card import Card


async def list_tags_with_counts(
    db: AsyncSession,
    parent_id: Optional[int] = None,
    search: Optional[str] = None,
    root_only: bool = False,
) -> list[dict]:
    """
    List tags with their card counts.
    - parent_id: filter to children of a specific parent tag
    - search: substring match on tag name (case-insensitive)
    - root_only: only return tags with no parent
    """
    count_subq = (
        select(CardTag.tag_id, func.count(CardTag.card_id).label("card_count"))
        .group_by(CardTag.tag_id)
        .subquery()
    )
    stmt = (
        select(Tag, func.coalesce(count_subq.c.card_count, 0).label("card_count"))
        .outerjoin(count_subq, count_subq.c.tag_id == Tag.id)
    )
    if root_only:
        stmt = stmt.where(Tag.parent_id.is_(None))
    elif parent_id is not None:
        stmt = stmt.where(Tag.parent_id == parent_id)
    if search:
        stmt = stmt.where(Tag.name.ilike(f"%{search}%"))
    stmt = stmt.order_by(Tag.name)
    result = await db.execute(stmt)
    return [
        {
            "id": row.Tag.id,
            "name": row.Tag.name,
            "description": row.Tag.description,
            "parent_id": row.Tag.parent_id,
            "card_count": row.card_count,
        }
        for row in result
    ]


async def get_tag_tree(db: AsyncSession) -> list[dict]:
    """
    Return all tags as a nested tree. Root tags contain a `children` list,
    each of which may itself have children, etc.
    """
    # Fetch all tags and counts in two queries to keep it simple
    count_subq = (
        select(CardTag.tag_id, func.count(CardTag.card_id).label("card_count"))
        .group_by(CardTag.tag_id)
        .subquery()
    )
    stmt = (
        select(Tag, func.coalesce(count_subq.c.card_count, 0).label("card_count"))
        .outerjoin(count_subq, count_subq.c.tag_id == Tag.id)
        .order_by(Tag.name)
    )
    result = await db.execute(stmt)
    rows = result.all()

    # Build flat map then assemble tree
    by_id: dict[int, dict] = {}
    for row in rows:
        by_id[row.Tag.id] = {
            "id": row.Tag.id,
            "name": row.Tag.name,
            "description": row.Tag.description,
            "parent_id": row.Tag.parent_id,
            "card_count": row.card_count,
            "children": [],
        }

    roots: list[dict] = []
    for node in by_id.values():
        if node["parent_id"] is None:
            roots.append(node)
        elif node["parent_id"] in by_id:
            by_id[node["parent_id"]]["children"].append(node)

    return roots


async def get_cards_by_tag(
    db: AsyncSession,
    tag_id: int,
    offset: int = 0,
    limit: int = 50,
    card_type: Optional[str] = None,
) -> list[dict]:
    """Cards (across all decks) that carry the given tag."""
    stmt = (
        select(Card)
        .join(CardTag, CardTag.card_id == Card.id)
        .where(CardTag.tag_id == tag_id)
    )
    if card_type:
        stmt = stmt.where(Card.card_type == card_type)
    stmt = stmt.order_by(Card.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return [_card_summary(c) for c in result.scalars().all()]


async def get_tag(db: AsyncSession, tag_id: int) -> Optional[Tag]:
    return await db.get(Tag, tag_id)


async def create_tag(
    db: AsyncSession,
    name: str,
    parent_id: Optional[int] = None,
    description: Optional[str] = None,
) -> Tag:
    tag = Tag(name=name, parent_id=parent_id, description=description)
    db.add(tag)
    await db.flush()
    return tag


async def update_tag(
    db: AsyncSession,
    tag: Tag,
    name: Optional[str] = None,
    parent_id: Optional[int] = None,
    description: Optional[str] = None,
) -> Tag:
    if name is not None:
        tag.name = name
    if parent_id is not None:
        tag.parent_id = parent_id
    if description is not None:
        tag.description = description
    await db.flush()
    return tag


async def delete_tag(db: AsyncSession, tag: Tag) -> None:
    await db.delete(tag)
    await db.flush()


def _card_summary(card: Card) -> dict:
    return {
        "id": card.id,
        "deck_id": card.deck_id,
        "thai": card.thai,
        "english": card.english,
        "card_type": card.card_type,
        "created_at": card.created_at.isoformat(),
    }
