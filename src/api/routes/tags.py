from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.db.services import tag_service

router = APIRouter(prefix="/tags", tags=["tags"])


class TagCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None
    description: Optional[str] = None


class TagUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[int] = None
    description: Optional[str] = None


class MergeBody(BaseModel):
    target_id: int


@router.get("")
async def list_tags(
    parent_id: Optional[int] = Query(None, description="Filter to children of this tag"),
    search: Optional[str] = Query(None, description="Substring search on tag name"),
    root_only: bool = Query(False, description="Return only root-level tags (no parent)"),
    db: AsyncSession = Depends(get_db),
):
    """List all tags with their card counts."""
    return await tag_service.list_tags_with_counts(
        db, parent_id=parent_id, search=search, root_only=root_only
    )


@router.get("/duplicates")
async def tag_duplicates(db: AsyncSession = Depends(get_db)):
    """Return pairs of tags that are likely duplicates."""
    return await tag_service.find_potential_duplicates(db)


@router.get("/tree")
async def tag_tree(db: AsyncSession = Depends(get_db)):
    """Return the full tag hierarchy as a nested tree."""
    return await tag_service.get_tag_tree(db)


@router.get("/{tag_id}/cards")
async def cards_by_tag(
    tag_id: int,
    card_type: Optional[str] = Query(None, description="Filter by card type"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Paginated list of cards (across all decks) that carry this tag."""
    tag = await tag_service.get_tag(db, tag_id)
    if not tag:
        raise HTTPException(404, "Tag not found")
    return await tag_service.get_cards_by_tag(
        db, tag_id, offset=offset, limit=limit, card_type=card_type
    )


@router.post("", status_code=201)
async def create_tag(payload: TagCreate, db: AsyncSession = Depends(get_db)):
    tag = await tag_service.create_tag(
        db, name=payload.name, parent_id=payload.parent_id, description=payload.description
    )
    await db.commit()
    return {"id": tag.id, "name": tag.name, "parent_id": tag.parent_id, "description": tag.description}


@router.patch("/{tag_id}")
async def update_tag(tag_id: int, payload: TagUpdate, db: AsyncSession = Depends(get_db)):
    tag = await tag_service.get_tag(db, tag_id)
    if not tag:
        raise HTTPException(404, "Tag not found")
    tag = await tag_service.update_tag(db, tag, **payload.model_dump(exclude_none=True))
    await db.commit()
    return {"id": tag.id, "name": tag.name, "parent_id": tag.parent_id, "description": tag.description}


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(tag_id: int, db: AsyncSession = Depends(get_db)):
    tag = await tag_service.get_tag(db, tag_id)
    if not tag:
        raise HTTPException(404, "Tag not found")
    await tag_service.delete_tag(db, tag)
    await db.commit()


@router.post("/{source_id}/merge")
async def merge_tags(
    source_id: int, payload: MergeBody, db: AsyncSession = Depends(get_db)
):
    """Merge source tag into target. Moves all cards, copies missing metadata, deletes source."""
    if source_id == payload.target_id:
        raise HTTPException(422, "source_id and target_id must be different")
    source = await tag_service.get_tag(db, source_id)
    if not source:
        raise HTTPException(404, f"Source tag {source_id} not found")
    target = await tag_service.get_tag(db, payload.target_id)
    if not target:
        raise HTTPException(404, f"Target tag {payload.target_id} not found")
    result = await tag_service.merge_tags(db, source_id, payload.target_id)
    await db.commit()
    return result
