"""
Per-card mastery: two independent signals (accuracy, retention) combined into an
interpretable band. Deterministic, DB-free — callers pass in raw review history and
FSRS schedule fields.
"""
import math
from datetime import datetime, timezone
from typing import Optional

# FSRS forgetting-curve constants (same curve py-fsrs uses internally): stability is
# defined as the number of days for retrievability to decay to 90%.
_FSRS_DECAY = -0.5
_FSRS_FACTOR = 0.9 ** (1 / _FSRS_DECAY) - 1  # = 19/81 ≈ 0.234568

BANDS = ("still_learning", "struggling", "fragile", "solid", "developing")


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def recency_weighted_again_rate(
    reviews: list[tuple[int, datetime]],
    now: datetime,
    half_life_days: float,
) -> float:
    """
    Fraction of reviews rated Again (1), weighting recent reviews more heavily via
    exponential decay on review age. `reviews` is a list of (rating, reviewed_at).
    Returns 0.0 for an empty history.
    """
    if not reviews:
        return 0.0
    decay = math.log(2) / half_life_days
    total_weight = 0.0
    again_weight = 0.0
    for rating, reviewed_at in reviews:
        age_days = max((now - _ensure_utc(reviewed_at)).total_seconds() / 86400, 0.0)
        weight = math.exp(-decay * age_days)
        total_weight += weight
        if rating == 1:
            again_weight += weight
    return again_weight / total_weight if total_weight > 0 else 0.0


def retrievability(
    stability: Optional[float],
    last_review: Optional[datetime],
    now: datetime,
) -> Optional[float]:
    """
    Current retrievability from the FSRS forgetting curve, given stability (days) and
    the last review timestamp. None if the card has never been reviewed.
    """
    if stability is None or stability <= 0 or last_review is None:
        return None
    elapsed_days = max((now - _ensure_utc(last_review)).total_seconds() / 86400, 0.0)
    return (1 + _FSRS_FACTOR * elapsed_days / stability) ** _FSRS_DECAY


def classify_band(
    *,
    review_count: int,
    again_rate: float,
    retrievability: Optional[float],
    stability: Optional[float],
    lapses: int,
    fsrs_state: str,
    settings,
) -> str:
    """
    Bands, in priority order:
      still_learning — below mastery_min_reviews reviews (excluded from strength/weakness verdicts)
      struggling     — high again-rate OR high lapses OR relearning with low retrievability
      solid          — low again-rate AND high stability/retrievability
      fragile        — decent accuracy but low stability (getting it right, not sticking)
      developing     — everything else
    """
    if review_count < settings.mastery_min_reviews:
        return "still_learning"

    is_struggling = (
        again_rate >= settings.mastery_again_rate_struggling
        or lapses >= settings.mastery_lapses_struggling
        or (
            fsrs_state == "relearning"
            and retrievability is not None
            and retrievability < settings.mastery_retrievability_struggling
        )
    )
    if is_struggling:
        return "struggling"

    is_solid = (
        again_rate <= settings.mastery_accuracy_solid_max_again_rate
        and stability is not None
        and stability >= settings.mastery_stability_fragile_days
        and (retrievability is None or retrievability >= settings.mastery_retrievability_solid)
    )
    if is_solid:
        return "solid"

    if stability is not None and stability < settings.mastery_stability_fragile_days:
        return "fragile"

    return "developing"


# Composite score used only for ranking groups (strengths/weaknesses), not shown as a
# standalone number to the learner — the band distribution is the interpretable output.
_BAND_SCORE = {"solid": 1.0, "developing": 0.66, "fragile": 0.33, "struggling": 0.0}


def mastery_score(band_counts: dict[str, int]) -> Optional[float]:
    """Mean band score over reviewed (non-still_learning) cards in a group."""
    reviewed = sum(n for band, n in band_counts.items() if band in _BAND_SCORE)
    if reviewed == 0:
        return None
    return sum(_BAND_SCORE[band] * n for band, n in band_counts.items() if band in _BAND_SCORE) / reviewed


def rank_groups(groups: list[dict], min_cards: int, top_n: int = 5) -> tuple[list[dict], list[dict]]:
    """
    Split dimension groups into (strengths, weaknesses), each capped at top_n and
    always disjoint — a group never appears in both lists. A group is only eligible
    once it has >= min_cards reviewed cards with a defined mastery_score — this is
    what keeps a thin group from being crowned a strength or weakness. Ineligible
    groups are omitted entirely (the caller renders them as "not enough data yet",
    not a bogus rank).

    With few eligible groups (fewer than 2 * top_n), the top/bottom windows would
    otherwise overlap — e.g. with only 2 eligible groups, the better one is
    trivially "the top group" AND the worse one is trivially "the bottom group",
    but naively taking top-N and bottom-N independently would show the better one
    as *also* a weakness and vice versa. Instead the two windows are shrunk to meet
    in the middle: only genuinely-top and genuinely-bottom groups are labelled,
    and anything in an odd middle group is left unranked rather than mislabeled.
    """
    eligible = sorted(
        (g for g in groups if g["reviewed_cards"] >= min_cards and g.get("mastery_score") is not None),
        key=lambda g: g["mastery_score"],
        reverse=True,
    )
    k = len(eligible)
    if k == 0:
        return [], []
    if k == 1:
        # A single eligible group can't be both a strength and a weakness — pick
        # a side by whether it's above or below the midpoint of the [0, 1] score.
        return ([eligible[0]], []) if eligible[0]["mastery_score"] >= 0.5 else ([], [eligible[0]])

    n_each = min(top_n, k // 2)
    strengths = eligible[:n_each]
    weaknesses = eligible[k - n_each:] if n_each > 0 else []
    return strengths, weaknesses
