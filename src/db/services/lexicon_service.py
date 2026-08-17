"""Read-only lookups against the shared Thai->English lexicon (Volubilis)."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.lexicon import Lexicon


async def lookup(db: AsyncSession, thai: str) -> list[str]:
    """Return distinct English translations for an exact Thai match, in row order."""
    result = await db.execute(
        select(Lexicon.english).where(Lexicon.thai == thai)
    )
    seen: set[str] = set()
    translations: list[str] = []
    for (english,) in result.all():
        if english not in seen:
            seen.add(english)
            translations.append(english)
    return translations


async def lookup_ranked(db: AsyncSession, thai: str) -> list[dict]:
    """Return distinct {english, level, pos} senses for an exact Thai match,
    in row order, for level-aware gloss sense selection."""
    result = await db.execute(
        select(Lexicon.english, Lexicon.level, Lexicon.pos)
        .where(Lexicon.thai == thai)
        .order_by(Lexicon.id)
    )
    seen: set[str] = set()
    senses: list[dict] = []
    for english, level, pos in result.all():
        if english not in seen:
            seen.add(english)
            senses.append({"english": english, "level": level, "pos": pos})
    return senses
