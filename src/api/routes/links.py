from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.db.models.card_link import LINK_TYPES
from src.db.services import link_service, link_suggestion_service

router = APIRouter(tags=["links"])


class LinkCreate(BaseModel):
    to_card_id: int
    link_type: str


@router.get("/cards/{card_id}/links")
async def get_card_links(card_id: int, db: AsyncSession = Depends(get_db)):
    """All outgoing and incoming links for a card, with linked card summaries."""
    return await link_service.get_card_links(db, card_id)


@router.post("/cards/{card_id}/links", status_code=501)
async def create_link(card_id: int, payload: LinkCreate):
    # TODO: implement link creation
    # if payload.link_type not in LINK_TYPES:
    #     raise HTTPException(
    #         422,
    #         f"Invalid link_type '{payload.link_type}'. Must be one of: {sorted(LINK_TYPES)}",
    #     )
    # if card_id == payload.to_card_id:
    #     raise HTTPException(422, "A card cannot link to itself")
    # link = await link_service.create_link(
    #     db,
    #     from_card_id=card_id,
    #     to_card_id=payload.to_card_id,
    #     link_type=payload.link_type,
    # )
    # await db.commit()
    # return {
    #     "link_id": link.id,
    #     "from_card_id": link.from_card_id,
    #     "to_card_id": link.to_card_id,
    #     "link_type": link.link_type,
    # }
    raise HTTPException(501, "Not implemented")


@router.delete("/cards/{card_id}/links/{link_id}", status_code=501)
async def delete_link(card_id: int, link_id: int):
    # TODO: implement link deletion
    # link = await link_service.get_link(db, link_id)
    # if not link:
    #     raise HTTPException(404, "Link not found")
    # if link.from_card_id != card_id and link.to_card_id != card_id:
    #     raise HTTPException(403, "This link does not belong to the specified card")
    # await link_service.delete_link(db, link_id)
    # await db.commit()
    raise HTTPException(501, "Not implemented")


@router.post("/cards/{card_id}/suggest-links", status_code=501)
async def suggest_links(card_id: int):
    # TODO: implement AI link suggestions
    # suggestions = await link_suggestion_service.suggest_links(db, card_id)
    # return {"card_id": card_id, "suggestions": suggestions}
    raise HTTPException(501, "Not implemented")
