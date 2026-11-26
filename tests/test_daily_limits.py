"""
Tests for daily new/review limits and catch-up mode:
src/db/services/daily_limits_service.py and the /review/session and
/review/summary routes that use it.

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_daily_limits.py -v
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.deps import get_db
from src.db.models import Base, Deck, Card
from src.db.models.card_schedule import CardSchedule
from src.db.models.review_log import ReviewLog
from src.db.services import daily_limits_service as dl
from src.db.services import preferences_service

NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

def _engine():
    return create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest_asyncio.fixture
async def db():
    engine = _engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    from src.main import app

    engine = _engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac, factory
    app.dependency_overrides.clear()
    await engine.dispose()


async def _deck(db, name="Deck"):
    deck = Deck(name=name)
    db.add(deck)
    await db.flush()
    return deck


async def _card(db, deck_id, i, state="new", due=None, stability=None, last_review=None):
    card = Card(deck_id=deck_id, thai=f"คำ{i}", english=f"word{i}", card_type="vocab")
    db.add(card)
    await db.flush()
    sched = CardSchedule(
        card_id=card.id,
        direction="th_to_en",
        fsrs_state=state,
        fsrs_due=due or NOW - timedelta(hours=1),
        fsrs_stability=stability,
        fsrs_last_review=last_review,
    )
    db.add(sched)
    await db.flush()
    return card, sched


async def _log(db, sched, state_before, when=None):
    db.add(ReviewLog(
        schedule_id=sched.id,
        rating=3,
        state_before=json.dumps({"state": state_before}),
        reviewed_at=when or NOW,
    ))
    await db.flush()


async def _set_limits(db, new=None, review=None):
    await preferences_service.update_preferences(db, daily_new_limit=new, daily_review_limit=review)


# ---------------------------------------------------------------------------
# day boundary
# ---------------------------------------------------------------------------

def test_day_start_utc_rolls_over_at_4am_local():
    # Bangkok (UTC+7, offset -420). 02:00 local on the 10th is still the 9th's day.
    now = datetime(2026, 11, 9, 19, 0, tzinfo=timezone.utc)  # 02:00 on the 10th, Bangkok
    start = dl.day_start_utc(-420, now)
    assert start == datetime(2026, 11, 8, 21, 0, tzinfo=timezone.utc)  # 04:00 on the 9th, Bangkok

    now = datetime(2026, 11, 9, 22, 0, tzinfo=timezone.utc)  # 05:00 on the 10th, Bangkok
    assert dl.day_start_utc(-420, now) == datetime(2026, 11, 9, 21, 0, tzinfo=timezone.utc)


def test_day_start_utc_default_is_utc():
    now = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
    assert dl.day_start_utc(0, now) == datetime(2026, 11, 9, 4, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("raw,expected", [(None, 0), ("-420", -420), ("60", 60), ("abc", 0), ("99999", 0)])
def test_parse_tz_offset(raw, expected):
    assert dl.parse_tz_offset(raw) == expected


# ---------------------------------------------------------------------------
# budget
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_budget_counts_todays_new_and_reviews(db):
    deck = await _deck(db)
    await _set_limits(db, new=5, review=50)
    _, s1 = await _card(db, deck.id, 1, state="learning")
    _, s2 = await _card(db, deck.id, 2, state="review", due=NOW + timedelta(days=3))
    _, s3 = await _card(db, deck.id, 3, state="review", due=NOW + timedelta(days=3))
    await _log(db, s1, "new")
    await _log(db, s1, "learning")  # learning steps count toward neither cap
    await _log(db, s2, "review")
    await _log(db, s3, "review")
    await _log(db, s3, "review", when=NOW - timedelta(days=2))  # an earlier day

    b = await dl.get_budget(db, now=NOW)
    assert (b.new_done, b.reviews_done) == (1, 2)
    assert (b.new_remaining, b.review_remaining) == (4, 48)
    assert b.catch_up is False


@pytest.mark.asyncio
async def test_catch_up_mode_pauses_new_cards(db):
    deck = await _deck(db)
    await _set_limits(db, new=10, review=10)
    for i in range(12):
        await _card(db, deck.id, i, state="review", stability=5.0, last_review=NOW - timedelta(days=10))
    b = await dl.get_budget(db, now=NOW)
    assert b.catch_up is True
    assert b.new_remaining == 0
    assert b.catch_up_days == 2


@pytest.mark.asyncio
async def test_extend_grants_more_new_and_lifts_review_cap(db):
    deck = await _deck(db)
    await _set_limits(db, new=1, review=10)
    _, s = await _card(db, deck.id, 0, state="learning")
    await _log(db, s, "new")
    b = await dl.get_budget(db, extend=True, now=NOW)
    assert b.new_remaining == dl.EXTEND_NEW_CARDS


# ---------------------------------------------------------------------------
# queue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_queue_caps_new_cards_and_reports_held_back(db):
    deck = await _deck(db)
    await _set_limits(db, new=3, review=100)
    for i in range(10):
        await _card(db, deck.id, i, state="new")
    for i in range(10, 12):
        await _card(db, deck.id, i, state="review")

    b = await dl.get_budget(db, now=NOW)
    q = await dl.get_due_queue(db, "deck", deck.id, "th_to_en", 20, b, now=NOW)
    assert (q.reviews, q.new) == (2, 3)
    assert q.held_back == 7
    # reviews come before new cards
    assert [s.fsrs_state for _, s in q.pairs] == ["review"] * 2 + ["new"] * 3


@pytest.mark.asyncio
async def test_queue_never_caps_learning_cards(db):
    deck = await _deck(db)
    await _set_limits(db, new=0, review=10)
    for i in range(4):
        await _card(db, deck.id, i, state="relearning")
    b = await dl.get_budget(db, now=NOW)
    q = await dl.get_due_queue(db, "library", None, "th_to_en", 20, b, now=NOW)
    assert q.learning == 4


@pytest.mark.asyncio
async def test_session_size_limit_is_not_reported_as_held_back(db):
    deck = await _deck(db)
    await _set_limits(db, new=100, review=100)
    for i in range(30):
        await _card(db, deck.id, i, state="new")
    b = await dl.get_budget(db, now=NOW)
    q = await dl.get_due_queue(db, "deck", deck.id, "th_to_en", 20, b, now=NOW)
    assert q.new == 20
    assert q.held_back == 0


@pytest.mark.asyncio
async def test_catch_up_queue_orders_most_salvageable_first(db):
    deck = await _deck(db)
    # elapsed/stability: a=10/2=5 (mostly forgotten), b=10/20=0.5 (still remembered), c=10/5=2
    a, _ = await _card(db, deck.id, 0, state="review", stability=2.0, last_review=NOW - timedelta(days=10))
    b, _ = await _card(db, deck.id, 1, state="review", stability=20.0, last_review=NOW - timedelta(days=10))
    c, _ = await _card(db, deck.id, 2, state="review", stability=5.0, last_review=NOW - timedelta(days=10))
    await _card(db, deck.id, 3, state="new")
    pairs = await dl.get_catch_up_queue(db, "th_to_en", now=NOW)
    assert [card.id for card, _ in pairs] == [b.id, c.id, a.id]


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

async def _seed_new(factory, n):
    async with factory() as db:
        deck = await _deck(db)
        for i in range(n):
            await _card(db, deck.id, i, state="new")
        await db.commit()
        return deck.id


@pytest.mark.asyncio
async def test_preferences_accept_and_validate_limits(client):
    ac, _ = client
    r = await ac.get("/api/preferences/")
    assert r.json()["daily_new_limit"] == 10 and r.json()["daily_review_limit"] == 100
    r = await ac.patch("/api/preferences/", json={"daily_new_limit": 5, "daily_review_limit": 200})
    assert r.status_code == 200 and r.json()["daily_new_limit"] == 5
    r = await ac.patch("/api/preferences/", json={"daily_review_limit": 1})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_summary_reports_capped_to_do_today(client):
    ac, factory = client
    await _seed_new(factory, 40)
    r = await ac.get("/api/review/summary", headers={"X-Timezone-Offset": "-420"})
    body = r.json()
    assert body["new_cards"] == 40
    assert body["to_do_today"] == 10
    assert body["today"]["new_remaining"] == 10
    assert body["today"]["catch_up"] is False


@pytest.mark.asyncio
async def test_session_respects_limit_then_extend_goes_past_it(client):
    ac, factory = client
    deck_id = await _seed_new(factory, 30)
    await ac.patch("/api/preferences/", json={"daily_new_limit": 2})

    r = await ac.post(f"/api/review/session?deck_id={deck_id}")
    body = r.json()
    assert body["total_cards"] == 2 and body["held_back"] == 28

    r = await ac.post(f"/api/review/session?deck_id={deck_id}&extend=true")
    assert r.json()["total_cards"] == dl.EXTEND_NEW_CARDS


@pytest.mark.asyncio
async def test_catch_up_strategy_session(client):
    ac, factory = client
    async with factory() as db:
        deck = await _deck(db)
        for i in range(40):
            await _card(db, deck.id, i, state="review", stability=3.0, last_review=NOW - timedelta(days=9))
        await db.commit()
    await ac.patch("/api/preferences/", json={"daily_review_limit": 10})

    summary = (await ac.get("/api/review/summary")).json()
    assert summary["today"]["catch_up"] is True and summary["today"]["catch_up_days"] == 4

    r = await ac.post("/api/review/session?scope=library&strategy=catch_up")
    assert r.json()["total_cards"] == dl.CATCH_UP_SESSION_SIZE
