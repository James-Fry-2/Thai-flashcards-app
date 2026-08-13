from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy import select, func, and_, not_, exists
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.db.models.card import Card
from src.db.models.card_link import CardLink
from src.db.models.card_schedule import CardSchedule
from src.db.models.deck import Deck
from src.db.models.review_log import ReviewLog
from src.db.models.tag import CardTag
from src.db.models.topic import CardTopic, Topic
from src.db.models.upload import Upload
from src.utils import mastery
from src.utils.current_user import current_user

_UTC = timezone.utc


async def get_untagged_cards(
    db: AsyncSession, deck_id: Optional[int] = None
) -> list[dict]:
    """Cards that have no tags, optionally filtered to a single deck."""
    stmt = select(Card).where(
        not_(exists(select(CardTag.card_id).where(CardTag.card_id == Card.id)))
    )
    if deck_id is not None:
        stmt = stmt.where(Card.deck_id == deck_id)
    stmt = stmt.order_by(Card.created_at.desc())
    result = await db.execute(stmt)
    return [_card_summary(c) for c in result.scalars().all()]


async def get_card_type_distribution(
    db: AsyncSession, deck_id: Optional[int] = None
) -> dict:
    """Count of cards per card_type (vocab / phrase / grammar)."""
    stmt = select(Card.card_type, func.count(Card.id).label("count"))
    if deck_id is not None:
        stmt = stmt.where(Card.deck_id == deck_id)
    stmt = stmt.group_by(Card.card_type)
    result = await db.execute(stmt)
    return {row.card_type: row.count for row in result}


async def get_fsrs_summary(
    db: AsyncSession, deck_id: Optional[int] = None
) -> list[dict]:
    """
    Average FSRS difficulty and stability, grouped by card_type and fsrs_state.
    Only includes schedules that have been reviewed at least once (difficulty is not null).
    """
    stmt = (
        select(
            Card.card_type,
            CardSchedule.fsrs_state,
            func.count(CardSchedule.id).label("count"),
            func.avg(CardSchedule.fsrs_difficulty).label("avg_difficulty"),
            func.avg(CardSchedule.fsrs_stability).label("avg_stability"),
            func.avg(CardSchedule.fsrs_lapses).label("avg_lapses"),
        )
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(CardSchedule.fsrs_difficulty.isnot(None))
    )
    if deck_id is not None:
        stmt = stmt.where(Card.deck_id == deck_id)
    stmt = stmt.group_by(Card.card_type, CardSchedule.fsrs_state)
    result = await db.execute(stmt)
    rows = result.all()
    return [
        {
            "card_type": row.card_type,
            "fsrs_state": row.fsrs_state,
            "count": row.count,
            "avg_difficulty": round(row.avg_difficulty, 3) if row.avg_difficulty else None,
            "avg_stability": round(row.avg_stability, 3) if row.avg_stability else None,
            "avg_lapses": round(row.avg_lapses, 2) if row.avg_lapses else None,
        }
        for row in rows
    ]


async def get_deck_coverage(db: AsyncSession) -> list[dict]:
    """
    Per-deck health metrics: card count, tagged/untagged split, new/due card counts.
    Excludes soft-deleted decks.
    """
    # Total cards per deck
    total_stmt = (
        select(Card.deck_id, func.count(Card.id).label("total"))
        .group_by(Card.deck_id)
        .subquery()
    )

    # Tagged cards per deck (cards that appear in card_tags at least once)
    tagged_stmt = (
        select(Card.deck_id, func.count(Card.id.distinct()).label("tagged"))
        .join(CardTag, CardTag.card_id == Card.id)
        .group_by(Card.deck_id)
        .subquery()
    )

    # New (never reviewed) card schedules per deck
    new_stmt = (
        select(Card.deck_id, func.count(CardSchedule.id).label("new_count"))
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(CardSchedule.fsrs_state == "new")
        .group_by(Card.deck_id)
        .subquery()
    )

    # Due (review state, due <= now) per deck
    now = datetime.now(_UTC)
    due_stmt = (
        select(Card.deck_id, func.count(CardSchedule.id).label("due_count"))
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .where(
            and_(
                CardSchedule.fsrs_state.in_(["review", "learning", "relearning"]),
                CardSchedule.fsrs_due <= now,
            )
        )
        .group_by(Card.deck_id)
        .subquery()
    )

    stmt = (
        select(
            Deck.id,
            Deck.name,
            func.coalesce(total_stmt.c.total, 0).label("total"),
            func.coalesce(tagged_stmt.c.tagged, 0).label("tagged"),
            func.coalesce(new_stmt.c.new_count, 0).label("new_count"),
            func.coalesce(due_stmt.c.due_count, 0).label("due_count"),
        )
        .outerjoin(total_stmt, total_stmt.c.deck_id == Deck.id)
        .outerjoin(tagged_stmt, tagged_stmt.c.deck_id == Deck.id)
        .outerjoin(new_stmt, new_stmt.c.deck_id == Deck.id)
        .outerjoin(due_stmt, due_stmt.c.deck_id == Deck.id)
        .where(Deck.deleted_at.is_(None))
        .order_by(Deck.name)
    )
    result = await db.execute(stmt)
    return [
        {
            "deck_id": row.id,
            "deck_name": row.name,
            "total_cards": row.total,
            "tagged_cards": row.tagged,
            "untagged_cards": row.total - row.tagged,
            "new_cards": row.new_count,
            "due_cards": row.due_count,
        }
        for row in result
    ]


async def get_at_risk_cards(
    db: AsyncSession,
    deck_id: Optional[int] = None,
    limit: int = 20,
    difficulty_threshold: float = 7.0,
    overdue_days: int = 14,
) -> list[dict]:
    """
    Cards with high FSRS difficulty that are significantly overdue.
    These are the highest-risk items for forgetting.
    """
    now = datetime.now(_UTC)
    cutoff = now - timedelta(days=overdue_days)
    stmt = (
        select(Card, CardSchedule, Deck.name.label("deck_name"))
        .join(CardSchedule, CardSchedule.card_id == Card.id)
        .join(Deck, Deck.id == Card.deck_id)
        .where(
            and_(
                CardSchedule.fsrs_difficulty >= difficulty_threshold,
                CardSchedule.fsrs_due <= cutoff,
                CardSchedule.fsrs_difficulty.isnot(None),
            )
        )
        .order_by(CardSchedule.fsrs_difficulty.desc())
        .limit(limit)
    )
    if deck_id is not None:
        stmt = stmt.where(Card.deck_id == deck_id)
    result = await db.execute(stmt)
    rows = result.all()
    return [
        {
            **_card_summary(row.Card),
            "schedule_id": row.CardSchedule.id,
            "deck_name": row.deck_name,
            "fsrs_difficulty": row.CardSchedule.fsrs_difficulty,
            "fsrs_stability": row.CardSchedule.fsrs_stability,
            "fsrs_state": row.CardSchedule.fsrs_state,
            "fsrs_lapses": row.CardSchedule.fsrs_lapses,
            "fsrs_due": row.CardSchedule.fsrs_due.isoformat() if row.CardSchedule.fsrs_due else None,
            "last_reviewed": row.CardSchedule.fsrs_last_review.isoformat() if row.CardSchedule.fsrs_last_review else None,
            "days_overdue": (now - row.CardSchedule.fsrs_due.replace(tzinfo=_UTC)).days if row.CardSchedule.fsrs_due else None,
            "direction": row.CardSchedule.direction,
        }
        for row in rows
    ]


def _card_summary(card: Card) -> dict:
    return {
        "id": card.id,
        "deck_id": card.deck_id,
        "thai": card.thai,
        "english": card.english,
        "card_type": card.card_type,
        "created_at": card.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Learner feedback / analytics — per-card mastery rolled up to topic/chapter/
# card_type, coverage, deterministic patterns, and a weekly trend.
# Deterministic aggregation only — no LLM, no migration (see src/utils/mastery.py
# for the pure classification logic this builds on).
# ---------------------------------------------------------------------------

MASTERY_DIRECTION = "th_to_en"  # only direction with active schedules today


@dataclass
class _CardMastery:
    card: Card
    schedule: CardSchedule
    review_count: int
    again_rate: float
    retrievability: Optional[float]
    band: str


async def _all_card_mastery(db: AsyncSession, direction: str = MASTERY_DIRECTION) -> list[_CardMastery]:
    """
    Per-card mastery for every card with a schedule in `direction`. Two queries total
    (schedules+cards, then all their review logs) regardless of library size.
    """
    settings = get_settings()
    now = datetime.now(_UTC)

    rows = await db.execute(
        select(CardSchedule, Card)
        .join(Card, Card.id == CardSchedule.card_id)
        .where(CardSchedule.direction == direction)
    )
    pairs = rows.all()
    if not pairs:
        return []

    schedule_ids = [s.id for s, _ in pairs]
    log_rows = await db.execute(
        select(ReviewLog.schedule_id, ReviewLog.rating, ReviewLog.reviewed_at)
        .where(ReviewLog.schedule_id.in_(schedule_ids))
    )
    logs_by_schedule: dict[int, list[tuple[int, datetime]]] = defaultdict(list)
    for schedule_id, rating, reviewed_at in log_rows:
        logs_by_schedule[schedule_id].append((rating, reviewed_at))

    results = []
    for schedule, card in pairs:
        logs = logs_by_schedule.get(schedule.id, [])
        review_count = len(logs)
        again_rate = mastery.recency_weighted_again_rate(
            logs, now, settings.mastery_recency_half_life_days
        )
        retr = mastery.retrievability(schedule.fsrs_stability, schedule.fsrs_last_review, now)
        band = mastery.classify_band(
            review_count=review_count,
            again_rate=again_rate,
            retrievability=retr,
            stability=schedule.fsrs_stability,
            lapses=schedule.fsrs_lapses,
            fsrs_state=schedule.fsrs_state,
            settings=settings,
        )
        results.append(
            _CardMastery(
                card=card, schedule=schedule, review_count=review_count,
                again_rate=again_rate, retrievability=retr, band=band,
            )
        )
    return results


async def _topic_root_map(db: AsyncSession) -> dict[int, Topic]:
    """Map every topic id to its top-level ancestor Topic (itself, if already a root)."""
    result = await db.execute(select(Topic))
    topics = {t.id: t for t in result.scalars().all()}

    root_cache: dict[int, Topic] = {}

    def root_of(tid: int) -> Topic:
        if tid in root_cache:
            return root_cache[tid]
        t = topics[tid]
        seen = {tid}
        while t.parent_id is not None and t.parent_id in topics and t.parent_id not in seen:
            seen.add(t.parent_id)
            t = topics[t.parent_id]
        root_cache[tid] = t
        return t

    return {tid: root_of(tid) for tid in topics}


async def _build_group_key_fn(db: AsyncSession, dimension: str):
    """
    Returns a function cm -> list[(group_id, group_name)] assigning a card's mastery
    row to zero or more dimension groups (a card can belong to multiple topics; it
    belongs to at most one chapter/card_type).
    """
    if dimension == "card_type":
        return lambda cm: [(cm.card.card_type, cm.card.card_type)]

    if dimension == "topic":
        topic_rows = await db.execute(select(CardTopic.card_id, CardTopic.topic_id))
        card_topic_ids: dict[int, set[int]] = defaultdict(set)
        for card_id, topic_id in topic_rows:
            card_topic_ids[card_id].add(topic_id)
        root_map = await _topic_root_map(db)

        def keys_for(cm: _CardMastery):
            tids = card_topic_ids.get(cm.card.id, set())
            roots = {root_map[tid] for tid in tids if tid in root_map}
            return [(r.id, r.name) for r in roots]

        return keys_for

    if dimension == "chapter":
        upload_rows = await db.execute(
            select(Upload.id, Upload.chapter_label, Upload.source_title, Upload.filename)
            .where(Upload.kind == "chapter_child")
        )
        chapter_labels = {
            uid: (chapter_label or source_title or filename)
            for uid, chapter_label, source_title, filename in upload_rows
        }

        def keys_for(cm: _CardMastery):
            uid = cm.card.source_upload_id
            if uid is None or uid not in chapter_labels:
                return []
            return [(uid, chapter_labels[uid])]

        return keys_for

    raise ValueError(f"Unknown dimension {dimension!r}")


def _empty_band_counts() -> dict[str, int]:
    return {b: 0 for b in mastery.BANDS}


async def mastery_by_dimension(
    db: AsyncSession,
    dimension: str,
    user: Optional[int] = None,
    _all_mastery: Optional[list[_CardMastery]] = None,
) -> dict:
    """
    Roll per-card mastery up to "topic" (child topics rolled into their root ancestor),
    "chapter" (grouped by the source chapter_child upload), or "card_type".

    `user` is accepted for forward-compat with multi-user/auth (see current_user()) —
    there is no per-user data yet, so it does not filter anything today.
    """
    if user is None:
        user = current_user()
    settings = get_settings()
    if _all_mastery is None:
        _all_mastery = await _all_card_mastery(db)

    key_fn = await _build_group_key_fn(db, dimension)

    groups: dict = {}
    for cm in _all_mastery:
        for key, name in key_fn(cm):
            g = groups.setdefault(key, {
                "id": key, "name": name, "total_cards": 0,
                "band_counts": _empty_band_counts(),
                "_accuracy_sum": 0.0, "_retention_sum": 0.0, "_retention_n": 0,
                "_weak_card_ids": [],
            })
            g["total_cards"] += 1
            g["band_counts"][cm.band] += 1
            if cm.band != "still_learning":
                g["_accuracy_sum"] += 1 - cm.again_rate
                if cm.retrievability is not None:
                    g["_retention_sum"] += cm.retrievability
                    g["_retention_n"] += 1
            if cm.band in ("struggling", "fragile"):
                g["_weak_card_ids"].append(cm.card.id)

    result_groups = []
    for g in groups.values():
        band_counts = g["band_counts"]
        reviewed = g["total_cards"] - band_counts["still_learning"]
        band_distribution = (
            {b: round(band_counts[b] / reviewed, 3) for b in ("solid", "developing", "fragile", "struggling")}
            if reviewed else {}
        )
        result_groups.append({
            "id": g["id"],
            "name": g["name"],
            "total_cards": g["total_cards"],
            "reviewed_cards": reviewed,
            "still_learning_count": band_counts["still_learning"],
            "band_distribution": band_distribution,
            "mean_accuracy": round(g["_accuracy_sum"] / reviewed, 3) if reviewed else None,
            "mean_retention": round(g["_retention_sum"] / g["_retention_n"], 3) if g["_retention_n"] else None,
            "mastery_score": mastery.mastery_score(band_counts),
            "eligible": reviewed >= settings.mastery_group_min_cards,
            # cards to target with a "study these" action — the ones flagged struggling/fragile
            "weak_card_ids": g["_weak_card_ids"][:200],
        })

    result_groups.sort(key=lambda g: g["name"])
    strengths, weaknesses = mastery.rank_groups(result_groups, settings.mastery_group_min_cards)

    return {"dimension": dimension, "groups": result_groups, "strengths": strengths, "weaknesses": weaknesses}


async def coverage_by_dimension(
    db: AsyncSession,
    dimension: str,
    _all_mastery: Optional[list[_CardMastery]] = None,
) -> list[dict]:
    """
    Unreviewed (fsrs_state="new") card counts per group — what the learner hasn't
    *started*, distinct from what they're weak at (mastery_by_dimension).
    """
    if _all_mastery is None:
        _all_mastery = await _all_card_mastery(db)

    key_fn = await _build_group_key_fn(db, dimension)

    counts: dict = {}
    for cm in _all_mastery:
        for key, name in key_fn(cm):
            c = counts.setdefault(key, {"id": key, "name": name, "total_cards": 0, "new_cards": 0})
            c["total_cards"] += 1
            if cm.schedule.fsrs_state == "new":
                c["new_cards"] += 1

    return sorted(
        [c for c in counts.values() if c["new_cards"] > 0],
        key=lambda c: c["new_cards"],
        reverse=True,
    )


def _maybe_add_pattern(
    patterns: list[dict],
    key: str,
    label: str,
    subgroup: list[_CardMastery],
    baseline: float,
    settings,
) -> None:
    if len(subgroup) < settings.pattern_min_reviewed_cards:
        return
    rate = sum(cm.again_rate for cm in subgroup) / len(subgroup)
    gap = rate - baseline
    if abs(gap) < settings.pattern_effect_size:
        return
    patterns.append({
        "key": key,
        "label": label,
        "subgroup_again_rate": round(rate, 3),
        "baseline_again_rate": round(baseline, 3),
        "gap": round(gap, 3),
        "sample_size": len(subgroup),
        "card_ids": [cm.card.id for cm in subgroup][:500],
    })


async def get_patterns(
    db: AsyncSession,
    user: Optional[int] = None,
    _all_mastery: Optional[list[_CardMastery]] = None,
) -> dict:
    """
    Deterministic, baseline-compared insights a learner can't easily see themselves:
    confusable-pair error share, script complexity, and the acquisition-vs-retention
    split (struggling = reteach; fragile = re-space — the two need opposite fixes).
    """
    if user is None:
        user = current_user()
    settings = get_settings()
    if _all_mastery is None:
        _all_mastery = await _all_card_mastery(db)

    reviewed = [cm for cm in _all_mastery if cm.band != "still_learning"]
    patterns: list[dict] = []
    baseline = None

    if reviewed:
        baseline = sum(cm.again_rate for cm in reviewed) / len(reviewed)

        confusable_ids = set(
            await db.scalars(
                select(CardLink.from_card_id).where(CardLink.link_type == "confusable").distinct()
            )
        )
        confusable_group = [cm for cm in reviewed if cm.card.id in confusable_ids]
        _maybe_add_pattern(patterns, "confusable_pairs", "Confusable pairs", confusable_group, baseline, settings)

        complex_group = [
            cm for cm in reviewed
            if cm.card.has_cluster or cm.card.has_rare_consonant or cm.card.has_silent_mark
        ]
        _maybe_add_pattern(
            patterns, "script_complexity",
            "Clusters, rare consonants, or silent marks", complex_group, baseline, settings,
        )

    struggling = [cm for cm in _all_mastery if cm.band == "struggling"]
    fragile = [cm for cm in _all_mastery if cm.band == "fragile"]
    acquisition_vs_retention = None
    if struggling and fragile:
        acquisition_vs_retention = {
            "struggling_count": len(struggling),
            "fragile_count": len(fragile),
            "struggling_card_ids": [cm.card.id for cm in struggling][:500],
            "fragile_card_ids": [cm.card.id for cm in fragile][:500],
        }

    return {
        "baseline_again_rate": round(baseline, 3) if baseline is not None else None,
        "patterns": patterns,
        "acquisition_vs_retention": acquisition_vs_retention,
    }


async def get_weekly_trend(
    db: AsyncSession, weeks: int = 12, user: Optional[int] = None
) -> list[dict]:
    """Weekly again-rate over ReviewLog history — one series, so 'doing well' reads as
    progress rather than a static grade. Weeks with zero reviews are included as gaps."""
    if user is None:
        user = current_user()
    now = datetime.now(_UTC)
    cutoff = now - timedelta(weeks=weeks)

    rows = await db.execute(
        select(ReviewLog.rating, ReviewLog.reviewed_at).where(ReviewLog.reviewed_at >= cutoff)
    )
    buckets: dict[tuple[int, int], dict] = {}
    for rating, reviewed_at in rows:
        if reviewed_at.tzinfo is None:
            reviewed_at = reviewed_at.replace(tzinfo=_UTC)
        iso_year, iso_week, _ = reviewed_at.isocalendar()
        key = (iso_year, iso_week)
        b = buckets.setdefault(key, {"reviews": 0, "again": 0})
        b["reviews"] += 1
        if rating == 1:
            b["again"] += 1

    result = []
    seen = set()
    cursor = cutoff
    while cursor <= now:
        iso_year, iso_week, _ = cursor.isocalendar()
        key = (iso_year, iso_week)
        if key not in seen:
            seen.add(key)
            b = buckets.get(key)
            result.append({
                "year": iso_year,
                "week": iso_week,
                "reviews": b["reviews"] if b else 0,
                "again_rate": round(b["again"] / b["reviews"], 3) if b and b["reviews"] else None,
            })
        cursor += timedelta(days=7)
    return result


async def get_progress(db: AsyncSession, user: Optional[int] = None) -> dict:
    """Bundle payload for the dashboard Insights panel: mastery roll-ups (with
    strengths/weaknesses) per dimension, coverage, patterns, and the trend series."""
    if user is None:
        user = current_user()
    all_mastery = await _all_card_mastery(db)

    return {
        "topic": await mastery_by_dimension(db, "topic", user=user, _all_mastery=all_mastery),
        "chapter": await mastery_by_dimension(db, "chapter", user=user, _all_mastery=all_mastery),
        "card_type": await mastery_by_dimension(db, "card_type", user=user, _all_mastery=all_mastery),
        "coverage": {
            "topic": await coverage_by_dimension(db, "topic", _all_mastery=all_mastery),
            "chapter": await coverage_by_dimension(db, "chapter", _all_mastery=all_mastery),
        },
        "patterns": await get_patterns(db, user=user, _all_mastery=all_mastery),
        "trend": await get_weekly_trend(db, user=user),
    }
