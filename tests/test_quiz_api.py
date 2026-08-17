"""
Integration tests for POST /quiz/session and POST /quiz/answer
(src/api/routes/quiz.py). Verifies the option-log writes and — the important
one — that a full quiz session never touches card_schedules or review_logs.

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_quiz_api.py -v
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base, Deck, Card
from src.db.models.card_schedule import CardSchedule
from src.db.models.review_log import ReviewLog
from src.db.models.quiz_option_log import QuizOptionLog
from src.api.deps import get_db


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


_FILLER_WORDS = ["book", "car", "tree", "river", "mountain", "chair", "table", "window"]


async def _seed_deck_with_cards(factory, n_fillers=6):
    async with factory() as db:
        deck = Deck(name="Test Deck")
        db.add(deck)
        await db.flush()
        target = Card(deck_id=deck.id, thai="แมว", english="cat", card_type="vocab")
        db.add(target)
        # Distinct single-word glosses so fillers are valid against each
        # other too, not just against the target.
        for i in range(n_fillers):
            db.add(Card(deck_id=deck.id, thai=f"เติม{i}", english=_FILLER_WORDS[i], card_type="vocab"))
        await db.commit()
        return deck.id, target.id


class TestQuizSessionAndAnswer:
    @pytest.mark.asyncio
    async def test_session_returns_four_option_items(self, client):
        ac, factory = client
        deck_id, target_id = await _seed_deck_with_cards(factory)

        resp = await ac.post("/api/quiz/session", params={"deck_id": deck_id, "limit": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["direction"] == "th_to_en"
        assert data["items"]
        item = next(i for i in data["items"] if i["card_id"] == target_id)
        assert len(item["options"]) == 4
        assert not any("thai" in o for o in item["options"])  # never leak option thai to the client

    @pytest.mark.asyncio
    async def test_answer_writes_four_log_rows_with_correct_flags(self, client):
        ac, factory = client
        deck_id, target_id = await _seed_deck_with_cards(factory)

        session_resp = await ac.post("/api/quiz/session", params={"deck_id": deck_id, "limit": 5})
        data = session_resp.json()
        item = next(i for i in data["items"] if i["card_id"] == target_id)
        chosen = item["options"][0]

        answer_resp = await ac.post("/api/quiz/answer", json={
            "quiz_session_id": data["quiz_session_id"],
            "target_card_id": item["card_id"],
            "chosen_card_id": chosen["card_id"],
            "latency_ms": 1234,
            "options": item["options"],
        })
        assert answer_resp.status_code == 200
        body = answer_resp.json()
        assert body["correct"] == (chosen["card_id"] == target_id)

        async with factory() as db:
            result = await db.execute(
                select(QuizOptionLog).where(QuizOptionLog.target_card_id == target_id)
            )
            rows = result.scalars().all()
            assert len(rows) == 4
            assert sum(r.was_chosen for r in rows) == 1
            assert sum(r.is_target for r in rows) == 1
            assert {r.position for r in rows} == {0, 1, 2, 3}
            assert all(r.quiz_session_id == data["quiz_session_id"] for r in rows)

    @pytest.mark.asyncio
    async def test_full_session_never_touches_schedule_or_review_log(self, client):
        """The important one: a full quiz session must leave FSRS state untouched."""
        ac, factory = client
        deck_id, target_id = await _seed_deck_with_cards(factory)

        async def _counts():
            async with factory() as db:
                sched = (await db.execute(select(func.count()).select_from(CardSchedule))).scalar()
                log = (await db.execute(select(func.count()).select_from(ReviewLog))).scalar()
                return sched, log

        before = await _counts()

        session_resp = await ac.post("/api/quiz/session", params={"deck_id": deck_id, "limit": 5})
        data = session_resp.json()
        for item in data["items"]:
            correct = next(o for o in item["options"] if o["card_id"] == item["card_id"])
            await ac.post("/api/quiz/answer", json={
                "quiz_session_id": data["quiz_session_id"],
                "target_card_id": item["card_id"],
                "chosen_card_id": correct["card_id"],
                "latency_ms": 500,
                "options": item["options"],
            })

        after = await _counts()
        assert after == before == (0, 0)


class TestThinPoolExclusion:
    @pytest.mark.asyncio
    async def test_thin_pool_card_excluded_from_session(self, client):
        ac, factory = client
        async with factory() as db:
            deck = Deck(name="Thin Deck")
            db.add(deck)
            await db.flush()
            target = Card(deck_id=deck.id, thai="แมว", english="cat", card_type="vocab")
            db.add(target)
            # Only one other card exists at all — not enough for 3 distractors.
            db.add(Card(deck_id=deck.id, thai="หนังสือ", english="book", card_type="vocab"))
            await db.commit()
            deck_id, target_id = deck.id, target.id

        resp = await ac.post("/api/quiz/session", params={"deck_id": deck_id, "limit": 5})
        data = resp.json()
        assert all(i["card_id"] != target_id for i in data["items"])
