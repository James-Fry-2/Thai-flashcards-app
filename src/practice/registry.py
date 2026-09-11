"""
Exercise-type registry for practice mode.

Adding a new exercise type should mean adding one `ExerciseType` entry to
REGISTRY — the session builder (src/db/services/practice_service.py), the
API routes, option logging, and the existing quiz/distractor tests all stay
untouched.

`is_eligible` is a cheap synchronous pre-filter (no db access); `build_payload`
is the expensive authoritative check and may still reject by returning None
(e.g. mc_th_en when the distractor slate comes back short) — that split
exists so the session builder doesn't do distractor work on cards it could
have rejected for free.

Exercise types under consideration but NOT implemented here — listed so the
registry's purpose (a slot for future formats, not a finished list) stays
legible:
  - cloze deletion over `example_thai`
  - typed production (learner types the Thai, not multiple choice)
  - audio identification
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.card import Card
from src.db.services import distractor_service


@dataclass(frozen=True)
class ExerciseType:
    key: str
    direction: str
    grading: str  # "binary" | "self_rated"
    is_eligible: Callable[[Card], bool]
    build_payload: Callable[[AsyncSession, Card], Awaitable[Optional[dict]]]


def _th_en_eligible(card: Card) -> bool:
    return bool(card.thai and card.english)


async def _mc_th_en_payload(db: AsyncSession, card: Card) -> Optional[dict]:
    slate = await distractor_service.build_option_slate(db, card.id, n_options=4)
    if len(slate) < 4:
        return None
    # thai is in the raw slate for logging/debug only — never send it to the
    # client, or the option itself gives the answer away.
    options = [
        {
            "card_id": o["card_id"],
            "english": o["english"],
            "source": o["source"],
            "position": o["position"],
        }
        for o in slate
    ]
    return {"options": options}


async def _recall_th_en_payload(db: AsyncSession, card: Card) -> Optional[dict]:
    return {}


MC_TH_EN = ExerciseType(
    key="mc_th_en",
    direction="th_to_en",
    grading="binary",
    is_eligible=_th_en_eligible,
    build_payload=_mc_th_en_payload,
)

RECALL_TH_EN = ExerciseType(
    key="recall_th_en",
    direction="th_to_en",
    grading="self_rated",
    is_eligible=_th_en_eligible,
    build_payload=_recall_th_en_payload,
)

REGISTRY: dict[str, ExerciseType] = {
    MC_TH_EN.key: MC_TH_EN,
    RECALL_TH_EN.key: RECALL_TH_EN,
}
