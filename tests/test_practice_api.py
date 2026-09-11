"""
Tests for the mixed practice mode: src/db/services/practice_service.py,
src/practice/registry.py, src/api/routes/practice.py, and the /quiz shim
(src/api/routes/quiz.py). Supersedes tests/test_quiz_api.py — no reference
to QuizOptionLog here, that table no longer exists (migration r9s0t1u2v3w4).

tests/test_distractor_service.py is deliberately untouched by this refactor
and is not duplicated here.

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_practice_api.py -v
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base, Deck, Card
from src.db.models.card_schedule import CardSchedule
from src.db.models.review_log import ReviewLog
from src.db.models.review_session import ReviewSession
from src.db.models.practice import PracticeSession, PracticeAttempt, PracticeOptionLog
from src.db.services.practice_service import build_session
from src.api.deps import get_db

_FILLER_WORDS = ["book", "car", "tree", "river", "mountain", "chair", "table", "window", "door", "cloud"]


# ---------------------------------------------------------------------------
# db fixture — real in-memory async sqlite, for direct practice_service calls
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


async def _make_deck(db, name="Test Deck"):
    deck = Deck(name=name)
    db.add(deck)
    await db.flush()
    return deck


async def _make_card(db, deck_id, thai, english, **kwargs):
    card = Card(deck_id=deck_id, thai=thai, english=english, card_type=kwargs.pop("card_type", "vocab"), **kwargs)
    db.add(card)
    await db.flush()
    return card


async def _make_filler_cards(db, deck_id, n):
    cards = []
    for i in range(n):
        c = await _make_card(db, deck_id, f"เติม{i}", _FILLER_WORDS[i % len(_FILLER_WORDS)] + str(i))
        cards.append(c)
    return cards


# ---------------------------------------------------------------------------
# client fixture — httpx + ASGI, for the actual API routes
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client():
    from src.main import app

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, factory

    app.dependency_overrides.clear()
    await engine.dispose()


async def _seed_deck_with_cards(factory, n_fillers=8):
    async with factory() as db:
        deck = Deck(name="Test Deck")
        db.add(deck)
        await db.flush()
        target = Card(deck_id=deck.id, thai="แมว", english="cat", card_type="vocab")
        db.add(target)
        for i in range(n_fillers):
            db.add(Card(
                deck_id=deck.id, thai=f"เติม{i}",
                english=_FILLER_WORDS[i % len(_FILLER_WORDS)] + str(i), card_type="vocab",
            ))
        await db.commit()
        return deck.id, target.id


# ---------------------------------------------------------------------------
# build_session — assignment behaviour (unit, direct db)
# ---------------------------------------------------------------------------

class TestBuildSessionAssignment:
    @pytest.mark.asyncio
    async def test_mc_share_lands_in_40_60_percent(self, db):
        """Cards eligible for both exercise types: assignment must be
        uniform-random, not familiarity-driven (decision 2). A biased split
        here would mean exercise type quietly correlates with something
        other than chance."""
        deck_a = await _make_deck(db, "Target Deck")
        deck_b = await _make_deck(db, "Filler Deck")
        target = await _make_card(db, deck_a.id, "แมว", "cat")
        await _make_filler_cards(db, deck_b.id, 10)  # plenty of valid MC distractors, library-wide pool

        total = 200
        mc_count = 0
        for _ in range(total):
            items = await build_session(db, scope_type="deck", scope_id=deck_a.id, limit=1, exercise_types=None)
            assert len(items) == 1
            if items[0]["exercise_type"] == "mc_th_en":
                mc_count += 1

        share = mc_count / total
        assert 0.40 <= share <= 0.60

    @pytest.mark.asyncio
    async def test_restricted_to_mc_returns_only_mc_items(self, db):
        deck = await _make_deck(db)
        await _make_filler_cards(db, deck.id, 10)

        items = await build_session(db, scope_type="deck", scope_id=deck.id, limit=10, exercise_types=["mc_th_en"])
        assert items
        assert all(i["exercise_type"] == "mc_th_en" for i in items)

    @pytest.mark.asyncio
    async def test_thin_slate_falls_back_to_recall_not_dropped(self, db):
        deck = await _make_deck(db)
        target = await _make_card(db, deck.id, "แมว", "cat")
        await _make_filler_cards(db, deck.id, 1)  # only 1 valid distractor -> MC slate stays < 4

        items = await build_session(db, scope_type="deck", scope_id=deck.id, limit=5, exercise_types=None)
        matches = [i for i in items if i["card_id"] == target.id]
        assert len(matches) == 1, "thin-slate card must not be dropped"
        assert matches[0]["exercise_type"] == "recall_th_en"

    @pytest.mark.asyncio
    async def test_no_duplicate_card_ids(self, db):
        deck = await _make_deck(db)
        await _make_filler_cards(db, deck.id, 15)

        items = await build_session(db, scope_type="deck", scope_id=deck.id, limit=15, exercise_types=None)
        ids = [i["card_id"] for i in items]
        assert len(ids) == len(set(ids))

    @pytest.mark.asyncio
    async def test_target_selection_draws_from_whole_id_range(self, db):
        """Regression test for the order_by(Card.id).limit(n).then-shuffle
        bias: in a library bigger than limit * 3, only the lowest-id cards
        were ever reachable. Randomising in SQL (func.random()) fixes it."""
        deck = await _make_deck(db)
        cards = await _make_filler_cards(db, deck.id, 200)

        seen_ids: set[int] = set()
        for _ in range(20):
            items = await build_session(db, scope_type="library", scope_id=None, limit=20, exercise_types=None)
            seen_ids.update(i["card_id"] for i in items)

        high_id_cards = {c.id for c in cards if c.id > 150}
        assert seen_ids & high_id_cards, "high-id cards should be reachable, not just the lowest ids"


# ---------------------------------------------------------------------------
# practice_option_log CheckConstraint (unit, direct db)
# ---------------------------------------------------------------------------

class TestPracticeOptionLogConstraint:
    @pytest.mark.asyncio
    async def test_check_constraint_rejects_both_option_card_id_and_text_null(self, db):
        deck = await _make_deck(db)
        card = await _make_card(db, deck.id, "แมว", "cat")
        session = PracticeSession(scope_type="library", scope_id=None, direction="th_to_en")
        db.add(session)
        await db.flush()
        attempt = PracticeAttempt(
            session_id=session.id, card_id=card.id, exercise_type="mc_th_en",
            direction="th_to_en", outcome=True, rating=None,
        )
        db.add(attempt)
        await db.flush()

        db.add(PracticeOptionLog(
            attempt_id=attempt.id, option_card_id=None, option_text=None,
            option_source="target", position=0, is_target=True, was_chosen=True,
        ))
        with pytest.raises(IntegrityError):
            await db.flush()


# ---------------------------------------------------------------------------
# API: field leakage per exercise type
# ---------------------------------------------------------------------------

class TestFieldLeakage:
    @pytest.mark.asyncio
    async def test_mc_omits_answer_fields_recall_includes_them(self, client):
        ac, factory = client
        deck_id, target_id = await _seed_deck_with_cards(factory)

        mc_resp = await ac.post(
            "/api/practice/session",
            params={"deck_id": deck_id, "limit": 20, "exercise_types": "mc_th_en"},
        )
        mc_item = next(i for i in mc_resp.json()["items"] if i["card_id"] == target_id)
        assert "english" not in mc_item
        assert "example_english" not in mc_item
        assert "compound_breakdown" not in mc_item
        assert not any("thai" in o for o in mc_item["payload"]["options"])

        recall_resp = await ac.post(
            "/api/practice/session",
            params={"deck_id": deck_id, "limit": 20, "exercise_types": "recall_th_en"},
        )
        recall_item = next(i for i in recall_resp.json()["items"] if i["card_id"] == target_id)
        assert recall_item["english"] == "cat"
        assert "compound_breakdown" in recall_item


# ---------------------------------------------------------------------------
# API: attempt writes
# ---------------------------------------------------------------------------

class TestAttemptWrites:
    @pytest.mark.asyncio
    async def test_mc_attempt_writes_attempt_and_four_option_rows(self, client):
        ac, factory = client
        deck_id, target_id = await _seed_deck_with_cards(factory)

        session_resp = await ac.post(
            "/api/practice/session",
            params={"deck_id": deck_id, "limit": 20, "exercise_types": "mc_th_en"},
        )
        data = session_resp.json()
        item = next(i for i in data["items"] if i["card_id"] == target_id)
        chosen = item["payload"]["options"][0]

        attempt_resp = await ac.post("/api/practice/attempt", json={
            "session_id": data["session_id"],
            "card_id": item["card_id"],
            "exercise_type": item["exercise_type"],
            "latency_ms": 1234,
            "chosen_card_id": chosen["card_id"],
            "options": item["payload"]["options"],
        })
        assert attempt_resp.status_code == 200
        assert attempt_resp.json()["correct"] == (chosen["card_id"] == target_id)

        async with factory() as db:
            attempts = (
                await db.execute(select(PracticeAttempt).where(PracticeAttempt.card_id == target_id))
            ).scalars().all()
            assert len(attempts) == 1
            assert attempts[0].outcome is not None
            assert attempts[0].rating is None

            rows = (
                await db.execute(select(PracticeOptionLog).where(PracticeOptionLog.attempt_id == attempts[0].id))
            ).scalars().all()
            assert len(rows) == 4
            assert sum(r.was_chosen for r in rows) == 1
            assert sum(r.is_target for r in rows) == 1
            assert {r.position for r in rows} == {0, 1, 2, 3}
            assert all(r.option_card_id is not None and r.option_text is None for r in rows)

    @pytest.mark.asyncio
    async def test_recall_attempt_writes_rating_row_and_no_option_logs(self, client):
        ac, factory = client
        deck_id, target_id = await _seed_deck_with_cards(factory)

        session_resp = await ac.post(
            "/api/practice/session",
            params={"deck_id": deck_id, "limit": 20, "exercise_types": "recall_th_en"},
        )
        data = session_resp.json()
        item = next(i for i in data["items"] if i["card_id"] == target_id)

        attempt_resp = await ac.post("/api/practice/attempt", json={
            "session_id": data["session_id"],
            "card_id": item["card_id"],
            "exercise_type": item["exercise_type"],
            "latency_ms": 800,
            "rating": 3,
        })
        assert attempt_resp.status_code == 200

        async with factory() as db:
            attempts = (
                await db.execute(select(PracticeAttempt).where(PracticeAttempt.card_id == target_id))
            ).scalars().all()
            assert len(attempts) == 1
            assert attempts[0].rating == 3
            assert attempts[0].outcome is None

            rows = (
                await db.execute(select(PracticeOptionLog).where(PracticeOptionLog.attempt_id == attempts[0].id))
            ).scalars().all()
            assert rows == []

    @pytest.mark.asyncio
    async def test_rating_on_mc_attempt_returns_422(self, client):
        ac, factory = client
        deck_id, target_id = await _seed_deck_with_cards(factory)

        session_resp = await ac.post(
            "/api/practice/session",
            params={"deck_id": deck_id, "limit": 20, "exercise_types": "mc_th_en"},
        )
        data = session_resp.json()
        item = next(i for i in data["items"] if i["card_id"] == target_id)

        resp = await ac.post("/api/practice/attempt", json={
            "session_id": data["session_id"],
            "card_id": item["card_id"],
            "exercise_type": item["exercise_type"],
            "latency_ms": 800,
            "rating": 3,
        })
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# API: FSRS untouched — acceptance test for the whole feature
# ---------------------------------------------------------------------------

class TestFSRSUntouched:
    @pytest.mark.asyncio
    async def test_full_mixed_session_never_touches_fsrs_tables(self, client):
        ac, factory = client
        deck_id, target_id = await _seed_deck_with_cards(factory)

        async def _counts():
            async with factory() as db:
                sched = (await db.execute(select(func.count()).select_from(CardSchedule))).scalar()
                log = (await db.execute(select(func.count()).select_from(ReviewLog))).scalar()
                rs = (await db.execute(select(func.count()).select_from(ReviewSession))).scalar()
                return sched, log, rs

        before = await _counts()

        session_resp = await ac.post("/api/practice/session", params={"deck_id": deck_id, "limit": 10})
        data = session_resp.json()
        for item in data["items"]:
            if item["exercise_type"] == "mc_th_en":
                correct = next(o for o in item["payload"]["options"] if o["card_id"] == item["card_id"])
                await ac.post("/api/practice/attempt", json={
                    "session_id": data["session_id"],
                    "card_id": item["card_id"],
                    "exercise_type": item["exercise_type"],
                    "latency_ms": 500,
                    "chosen_card_id": correct["card_id"],
                    "options": item["payload"]["options"],
                })
            else:
                await ac.post("/api/practice/attempt", json={
                    "session_id": data["session_id"],
                    "card_id": item["card_id"],
                    "exercise_type": item["exercise_type"],
                    "latency_ms": 500,
                    "rating": 3,
                })
        await ac.post(f"/api/practice/session/{data['session_id']}/end")

        after = await _counts()
        assert after == before == (0, 0, 0)


# ---------------------------------------------------------------------------
# API: /quiz shim
# ---------------------------------------------------------------------------

class TestQuizShim:
    @pytest.mark.asyncio
    async def test_quiz_session_returns_mc_only_and_attempts_land_in_practice_attempts(self, client):
        ac, factory = client
        deck_id, target_id = await _seed_deck_with_cards(factory)

        resp = await ac.post("/api/quiz/session", params={"deck_id": deck_id, "limit": 20})
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"]
        assert all(i["exercise_type"] == "mc_th_en" for i in data["items"])

        item = next(i for i in data["items"] if i["card_id"] == target_id)
        chosen = item["payload"]["options"][0]

        answer_resp = await ac.post("/api/quiz/answer", json={
            "session_id": data["session_id"],
            "card_id": item["card_id"],
            "exercise_type": item["exercise_type"],
            "latency_ms": 500,
            "chosen_card_id": chosen["card_id"],
            "options": item["payload"]["options"],
        })
        assert answer_resp.status_code == 200

        async with factory() as db:
            rows = (
                await db.execute(select(PracticeAttempt).where(PracticeAttempt.card_id == target_id))
            ).scalars().all()
            assert len(rows) == 1


# ---------------------------------------------------------------------------
# API: distractor pool is library-wide regardless of session scope
# ---------------------------------------------------------------------------

class TestDistractorPoolIsLibraryWide:
    @pytest.mark.asyncio
    async def test_mc_distractors_come_from_outside_the_scoped_deck(self, client):
        ac, factory = client
        async with factory() as db:
            deck_x = Deck(name="Deck X")
            deck_y = Deck(name="Deck Y")
            db.add_all([deck_x, deck_y])
            await db.flush()
            target = Card(deck_id=deck_x.id, thai="แมว", english="cat", card_type="vocab")
            db.add(target)
            y_cards = []
            for i in range(8):
                c = Card(
                    deck_id=deck_y.id, thai=f"เติม{i}",
                    english=_FILLER_WORDS[i] + str(i), card_type="vocab",
                )
                db.add(c)
                y_cards.append(c)
            await db.commit()
            deck_x_id, target_id = deck_x.id, target.id
            y_card_ids = {c.id for c in y_cards}

        resp = await ac.post(
            "/api/practice/session",
            params={"deck_id": deck_x_id, "limit": 5, "exercise_types": "mc_th_en"},
        )
        data = resp.json()
        item = next(i for i in data["items"] if i["card_id"] == target_id)
        option_ids = {o["card_id"] for o in item["payload"]["options"]}
        assert option_ids & y_card_ids
