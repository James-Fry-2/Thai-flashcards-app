import re
from typing import Optional
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.tag import Tag, CardTag
from src.db.models.card import Card
from src.utils.text import levenshtein as _levenshtein


def _normalize_name(name: str) -> str:
    n = name.strip().lower()
    n = re.sub(r'[^\w\s]', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    if n.endswith('s') and len(n) > 2:
        n = n[:-1]
    return n


def _is_contained_word(shorter: str, longer: str) -> bool:
    return bool(re.search(r'\b' + re.escape(shorter) + r'\b', longer, re.IGNORECASE))


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
    from src.db.services import embedding_service
    tag = Tag(name=name, parent_id=parent_id, description=description)
    db.add(tag)
    await db.flush()
    await embedding_service.embed_tag(db, tag.id)
    return tag


async def update_tag(
    db: AsyncSession,
    tag: Tag,
    name: Optional[str] = None,
    parent_id: Optional[int] = None,
    description: Optional[str] = None,
) -> Tag:
    from src.db.services import embedding_service
    text_changed = name is not None or description is not None
    if name is not None:
        tag.name = name
    if parent_id is not None:
        tag.parent_id = parent_id
    if description is not None:
        tag.description = description
    await db.flush()
    if text_changed:
        await embedding_service.embed_tag(db, tag.id)
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


async def merge_tags(db: AsyncSession, source_id: int, target_id: int) -> dict:
    source = await db.get(Tag, source_id)
    target = await db.get(Tag, target_id)

    # Fix dangling FK: if target's parent points to source, null it before we delete source
    if target.parent_id == source_id:
        target.parent_id = None
        await db.flush()

    target_existing_result = await db.execute(
        select(CardTag.card_id).where(CardTag.tag_id == target_id)
    )
    already_in_target = {row[0] for row in target_existing_result}

    source_ct_result = await db.execute(
        select(CardTag).where(CardTag.tag_id == source_id)
    )
    source_cts = source_ct_result.scalars().all()

    cards_moved = 0
    cards_already_present = 0

    for ct in source_cts:
        if ct.card_id in already_in_target:
            await db.delete(ct)
            cards_already_present += 1
        else:
            ct.tag_id = target_id
            cards_moved += 1

    await db.flush()

    if not target.description and source.description:
        target.description = source.description
    if target.parent_id is None and source.parent_id is not None:
        if source.parent_id != target.id:
            target.parent_id = source.parent_id
    await db.flush()

    await db.delete(source)
    await db.flush()

    return {
        "merged": True,
        "target_id": target_id,
        "cards_moved": cards_moved,
        "cards_already_present": cards_already_present,
    }


async def find_potential_duplicates(db: AsyncSession, embedding_threshold: float = 0.85) -> list[dict]:
    from src.db.services import embedding_service

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
    tags = [
        {"id": row.Tag.id, "name": row.Tag.name, "card_count": row.card_count}
        for row in result
    ]

    pairs: dict[tuple[int, int], dict] = {}

    def _add_pair(a: dict, b: dict, reason: str, score: float) -> None:
        key = (min(a["id"], b["id"]), max(a["id"], b["id"]))
        lo = a if a["id"] < b["id"] else b
        hi = b if a["id"] < b["id"] else a
        if key not in pairs:
            pairs[key] = {"tag_a": lo, "tag_b": hi, "reasons": [reason], "score": score}
        else:
            if reason not in pairs[key]["reasons"]:
                pairs[key]["reasons"].append(reason)
            pairs[key]["score"] = max(pairs[key]["score"], score)

    # Deterministic rules (score=1.0)
    for i, a in enumerate(tags):
        a_norm = _normalize_name(a["name"])
        for b in tags[i + 1:]:
            b_norm = _normalize_name(b["name"])
            if a_norm == b_norm:
                _add_pair(a, b, "same normalized name", 1.0)
            elif _levenshtein(a_norm, b_norm) <= 2:
                dist = _levenshtein(a_norm, b_norm)
                _add_pair(a, b, f"similar name (edit distance {dist})", 1.0)
            else:
                a_lower = a["name"].lower()
                b_lower = b["name"].lower()
                if len(a_lower) != len(b_lower):
                    shorter = a_lower if len(a_lower) < len(b_lower) else b_lower
                    longer = b_lower if len(a_lower) < len(b_lower) else a_lower
                    if _is_contained_word(shorter, longer):
                        _add_pair(a, b, "one name contains the other", 1.0)

    # Embedding-based detection (additive)
    tag_by_id = {t["id"]: t for t in tags}
    emb_pairs = await embedding_service.find_duplicate_tag_candidates(
        db, min_similarity=embedding_threshold
    )
    for ep in emb_pairs:
        a = tag_by_id.get(ep["tag_a"]["id"])
        b = tag_by_id.get(ep["tag_b"]["id"])
        if a and b:
            sim = ep["similarity"]
            _add_pair(a, b, f"embedding similarity: {sim:.2f}", sim)

    output = []
    for p in pairs.values():
        output.append({
            "tag_a": p["tag_a"],
            "tag_b": p["tag_b"],
            "reason": "; ".join(p["reasons"]),
            "score": p["score"],
        })

    return sorted(output, key=lambda p: p["score"], reverse=True)
