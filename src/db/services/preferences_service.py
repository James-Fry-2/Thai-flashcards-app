"""Singleton user-preferences: get, update, and set-based effective-romanization swap."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import case, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.card import Card
from src.db.models.preferences import UserPreferences

_DEFAULT_DISPLAY = "source"
_DEFAULT_FALLBACK = "paiboon"

VALID_DISPLAY = {"source", "paiboon", "rtgs", "ipa"}
VALID_FALLBACK = {"paiboon", "rtgs", "ipa", "none"}


async def get_preferences(db: AsyncSession) -> UserPreferences:
    """Return the singleton row, creating it with defaults if absent."""
    prefs = await db.get(UserPreferences, 1)
    if prefs is None:
        prefs = UserPreferences(
            id=1,
            romanization_display=_DEFAULT_DISPLAY,
            romanization_fallback=_DEFAULT_FALLBACK,
        )
        db.add(prefs)
        await db.flush()
    return prefs


async def update_preferences(
    db: AsyncSession,
    romanization_display: Optional[str] = None,
    romanization_fallback: Optional[str] = None,
) -> UserPreferences:
    """Update preferences and, if romanization settings changed, recompute effective columns."""
    prefs = await get_preferences(db)

    rom_changed = False
    if romanization_display is not None:
        if romanization_display not in VALID_DISPLAY:
            raise ValueError(
                f"romanization_display must be one of {sorted(VALID_DISPLAY)}"
            )
        if prefs.romanization_display != romanization_display:
            prefs.romanization_display = romanization_display
            rom_changed = True

    if romanization_fallback is not None:
        if romanization_fallback not in VALID_FALLBACK:
            raise ValueError(
                f"romanization_fallback must be one of {sorted(VALID_FALLBACK)}"
            )
        if prefs.romanization_fallback != romanization_fallback:
            prefs.romanization_fallback = romanization_fallback
            rom_changed = True

    prefs.updated_at = datetime.now(timezone.utc)
    await db.flush()

    if rom_changed:
        await _swap_effective_romanization(db, prefs)

    return prefs


async def _swap_effective_romanization(db: AsyncSession, prefs: UserPreferences) -> None:
    """Set-based UPDATE: recompute cards.romanization from stored scheme columns.

    A CASE expression evaluates the full precedence chain for every row in a
    single SQL statement — no per-card Python loop.
    """
    display = prefs.romanization_display
    fallback = prefs.romanization_fallback

    display_col = getattr(Card, f"romanization_{display}")

    whens = [
        (Card.romanization_manual.isnot(None) & (Card.romanization_manual != ""),
         Card.romanization_manual),
        (display_col.isnot(None) & (display_col != ""),
         display_col),
    ]

    if fallback != "none":
        fallback_col = getattr(Card, f"romanization_{fallback}")
        whens.append(
            (fallback_col.isnot(None) & (fallback_col != ""), fallback_col)
        )

    await db.execute(
        update(Card).values(romanization=case(*whens, else_=None))
    )
