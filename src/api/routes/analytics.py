from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.db.services import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/untagged")
async def untagged_cards(
    deck_id: Optional[int] = Query(None, description="Filter to a specific deck"),
    db: AsyncSession = Depends(get_db),
):
    """Cards that have no tags. Use to find content that needs categorisation."""
    return await analytics_service.get_untagged_cards(db, deck_id=deck_id)


@router.get("/distribution")
async def card_type_distribution(
    deck_id: Optional[int] = Query(None, description="Filter to a specific deck"),
    db: AsyncSession = Depends(get_db),
):
    """Count of cards per type (vocab / phrase / grammar)."""
    return await analytics_service.get_card_type_distribution(db, deck_id=deck_id)


@router.get("/fsrs-summary")
async def fsrs_summary(
    deck_id: Optional[int] = Query(None, description="Filter to a specific deck"),
    db: AsyncSession = Depends(get_db),
):
    """
    Average FSRS difficulty, stability, and lapses grouped by card type and review state.
    Only cards that have been reviewed at least once are included.
    """
    return await analytics_service.get_fsrs_summary(db, deck_id=deck_id)


@router.get("/deck-coverage")
async def deck_coverage(db: AsyncSession = Depends(get_db)):
    """
    Per-deck health metrics: total cards, tagged/untagged split, new and due card counts.
    """
    return await analytics_service.get_deck_coverage(db)


@router.get("/progress")
async def progress(db: AsyncSession = Depends(get_db)):
    """
    Learner feedback bundle for the dashboard Insights panel: mastery roll-ups
    (band distribution, strengths/weaknesses) by topic, chapter, and card type;
    unreviewed coverage; deterministic patterns; and a weekly again-rate trend.
    """
    return await analytics_service.get_progress(db)


@router.get("/at-risk")
async def at_risk_cards(
    deck_id: Optional[int] = Query(None, description="Filter to a specific deck"),
    limit: int = Query(20, ge=1, le=100),
    difficulty_threshold: float = Query(7.0, ge=0.0, le=10.0, description="Minimum FSRS difficulty"),
    overdue_days: int = Query(14, ge=1, description="Minimum days overdue"),
    db: AsyncSession = Depends(get_db),
):
    """
    Cards with high FSRS difficulty that are significantly overdue — the highest-risk
    items for forgetting. Sorted by difficulty descending.
    """
    return await analytics_service.get_at_risk_cards(
        db,
        deck_id=deck_id,
        limit=limit,
        difficulty_threshold=difficulty_threshold,
        overdue_days=overdue_days,
    )
