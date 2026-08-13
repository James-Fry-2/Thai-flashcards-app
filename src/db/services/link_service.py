from typing import Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.card import Card
from src.db.models.card_link import CardLink, SYMMETRIC_LINK_TYPES
from src.db.models.base import utcnow


async def get_card_links(db: AsyncSession, card_id: int) -> dict:
    """
    Return all links for a card, split into outgoing and incoming.
    Each entry includes a summary of the linked card.
    """
    # Outgoing: card is the source
    out_result = await db.execute(
        select(CardLink).where(CardLink.from_card_id == card_id)
    )
    outgoing_links = out_result.scalars().all()

    # Incoming: card is the target
    in_result = await db.execute(
        select(CardLink).where(CardLink.to_card_id == card_id)
    )
    incoming_links = in_result.scalars().all()

    # Load linked card summaries
    async def _card_info(c_id: int) -> dict:
        card = await db.get(Card, c_id)
        if not card:
            return {"id": c_id}
        return {
            "id": card.id,
            "deck_id": card.deck_id,
            "thai": card.thai,
            "english": card.english,
            "card_type": card.card_type,
        }

    outgoing = []
    for link in outgoing_links:
        outgoing.append({
            "link_id": link.id,
            "link_type": link.link_type,
            "note": link.note,
            "card": await _card_info(link.to_card_id),
        })

    incoming = []
    for link in incoming_links:
        incoming.append({
            "link_id": link.id,
            "link_type": link.link_type,
            "note": link.note,
            "card": await _card_info(link.from_card_id),
        })

    return {"outgoing": outgoing, "incoming": incoming}


async def create_link(
    db: AsyncSession,
    from_card_id: int,
    to_card_id: int,
    link_type: str,
    note: Optional[str] = None,
) -> CardLink:
    """
    Create a link from from_card_id → to_card_id.
    For symmetric link types (related, antonym, confusable), also inserts the reverse direction.
    Silently ignores the insert if the link already exists (unique constraint).

    `note` is provenance: auto-detection passes set it (e.g. a confusable
    pass's detection reason); user-created links leave it None so re-runs of
    those passes can distinguish and preserve hand-made links.
    """
    now = utcnow()
    link = CardLink(
        from_card_id=from_card_id,
        to_card_id=to_card_id,
        link_type=link_type,
        note=note,
        created_at=now,
    )
    db.add(link)
    await db.flush()

    if link_type in SYMMETRIC_LINK_TYPES:
        # Check if reverse already exists to avoid constraint violation
        existing = await db.scalar(
            select(CardLink).where(
                CardLink.from_card_id == to_card_id,
                CardLink.to_card_id == from_card_id,
                CardLink.link_type == link_type,
            )
        )
        if not existing:
            reverse = CardLink(
                from_card_id=to_card_id,
                to_card_id=from_card_id,
                link_type=link_type,
                note=note,
                created_at=now,
            )
            db.add(reverse)
            await db.flush()

    return link


async def delete_link(db: AsyncSession, link_id: int) -> bool:
    """Delete a specific link by id. Returns True if deleted, False if not found."""
    link = await db.get(CardLink, link_id)
    if not link:
        return False
    await db.delete(link)
    await db.flush()
    return True


async def get_link(db: AsyncSession, link_id: int) -> Optional[CardLink]:
    return await db.get(CardLink, link_id)


async def get_unlinked_cards(
    db: AsyncSession, deck_id: Optional[int] = None
) -> list[dict]:
    """Cards that have no outgoing or incoming links."""
    from sqlalchemy import not_, exists

    stmt = select(Card).where(
        not_(
            exists(
                select(CardLink.id).where(
                    (CardLink.from_card_id == Card.id) | (CardLink.to_card_id == Card.id)
                )
            )
        )
    )
    if deck_id is not None:
        stmt = stmt.where(Card.deck_id == deck_id)
    stmt = stmt.order_by(Card.created_at.desc())
    result = await db.execute(stmt)
    cards = result.scalars().all()
    return [
        {
            "id": c.id,
            "deck_id": c.deck_id,
            "thai": c.thai,
            "english": c.english,
            "card_type": c.card_type,
        }
        for c in cards
    ]
