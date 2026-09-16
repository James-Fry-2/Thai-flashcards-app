"""
Tests for src/api/routes/triage.py — the card triage queue, batch AI checks,
decisions, and undo, exercised through the real ASGI app. No network calls:
LLM-touching routes patch the provider or the per-card service directly.

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_triage_routes.py -v
"""
import json
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.api.deps import get_db
from src.db.database import get_session_factory
from src.db.models import Base, Card, Deck
from src.db.models.card_flag import CardFlag
from src.utils.card_overrides import upsert_flag, upsert_override


@pytest_asyncio.fixture
async def client(monkeypatch):
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

    # triage.py's batch routes open their own sessions via
    # get_session_factory() instead of the injected `db` (concurrent tasks
    # can't safely share one AsyncSession) — point that at the same
    # in-memory engine so batch routes see the seeded data too.
    monkeypatch.setattr("src.api.routes.triage.get_session_factory", lambda: factory)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, factory

    app.dependency_overrides.clear()
    await engine.dispose()


async def _seed_card(
    factory, thai="แมว", english="cat", translation_status="unverified",
    translation_candidates=None, compound_breakdown=None, is_compound=None,
):
    async with factory() as db:
        deck = Deck(name="Test Deck")
        db.add(deck)
        await db.flush()
        card = Card(
            deck_id=deck.id, thai=thai, english=english, card_type="vocab",
            translation_status=translation_status,
            translation_candidates=json.dumps(translation_candidates) if translation_candidates else None,
            compound_breakdown=json.dumps(compound_breakdown, ensure_ascii=False) if compound_breakdown else None,
            is_compound=is_compound,
        )
        db.add(card)
        await db.commit()
        await db.refresh(card)
        return card.id


# ---------------------------------------------------------------------------
# GET /triage/queue
# ---------------------------------------------------------------------------

class TestTriageQueue:
    @pytest.mark.asyncio
    async def test_flagged_translation_appears_in_translation_group(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, english="bicycle", translation_status="flagged")

        resp = await ac.get("/api/triage/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert data["counts"]["translation"] == 1
        assert data["groups"]["translation"][0]["card_id"] == card_id

    @pytest.mark.asyncio
    async def test_translation_with_existing_override_is_excluded(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, english="bicycle", translation_status="flagged")
        async with factory() as db:
            await upsert_override(db, 1, card_id, "translation", {"english": "train"})
            await db.commit()

        resp = await ac.get("/api/triage/queue")
        data = resp.json()
        assert data["counts"]["translation"] == 0

    @pytest.mark.asyncio
    async def test_compound_gap_includes_missing_parts(self, client):
        ac, factory = client
        breakdown = [
            {"thai": "น้ำ", "gloss": "water", "gloss_source": "card"},
            {"thai": "แข็ง", "gloss": None, "gloss_source": None},
        ]
        card_id = await _seed_card(
            factory, thai="น้ำแข็ง", english="ice",
            compound_breakdown=breakdown, is_compound=True,
        )

        resp = await ac.get("/api/triage/queue")
        data = resp.json()
        assert data["counts"]["compound_gap"] == 1
        item = data["groups"]["compound_gap"][0]
        assert item["card_id"] == card_id
        assert item["missing_parts"] == ["แข็ง"]

    @pytest.mark.asyncio
    async def test_compound_gap_excludes_fully_glossed_cards(self, client):
        ac, factory = client
        breakdown = [
            {"thai": "น้ำ", "gloss": "water", "gloss_source": "card"},
            {"thai": "แข็ง", "gloss": "hard", "gloss_source": "lexicon"},
        ]
        await _seed_card(
            factory, thai="น้ำแข็ง", english="ice",
            compound_breakdown=breakdown, is_compound=True,
        )

        resp = await ac.get("/api/triage/queue")
        assert resp.json()["counts"]["compound_gap"] == 0

    @pytest.mark.asyncio
    async def test_compound_gap_excludes_suppressed_cards(self, client):
        ac, factory = client
        breakdown = [{"thai": "น้ำ", "gloss": None, "gloss_source": None}]
        card_id = await _seed_card(
            factory, thai="น้ำแข็ง", english="ice",
            compound_breakdown=breakdown, is_compound=True,
        )
        async with factory() as db:
            await upsert_override(db, 1, card_id, "compound", {"suppressed": True})
            await db.commit()

        resp = await ac.get("/api/triage/queue")
        assert resp.json()["counts"]["compound_gap"] == 0

    @pytest.mark.asyncio
    async def test_open_flag_not_covered_by_other_groups_appears(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, english="cat")
        async with factory() as db:
            await upsert_flag(db, 1, card_id, "romanization", "sounds off")
            await db.commit()

        resp = await ac.get("/api/triage/queue")
        data = resp.json()
        assert data["counts"]["open_flags"] == 1
        assert data["groups"]["open_flags"][0]["target"] == "romanization"

    @pytest.mark.asyncio
    async def test_open_compound_flag_already_in_compound_gap_is_not_duplicated(self, client):
        ac, factory = client
        breakdown = [{"thai": "น้ำ", "gloss": None, "gloss_source": None}]
        card_id = await _seed_card(
            factory, thai="น้ำแข็ง", english="ice",
            compound_breakdown=breakdown, is_compound=True,
        )
        async with factory() as db:
            await upsert_flag(db, 1, card_id, "compound", "AI review found an issue")
            await db.commit()

        resp = await ac.get("/api/triage/queue")
        data = resp.json()
        assert data["counts"]["compound_gap"] == 1
        assert data["counts"]["open_flags"] == 0


# ---------------------------------------------------------------------------
# POST /triage/verify-translations
# ---------------------------------------------------------------------------

class TestVerifyTranslationsBatch:
    @pytest.mark.asyncio
    async def test_over_50_ids_is_422(self, client):
        ac, factory = client
        resp = await ac.post("/api/triage/verify-translations", json={"card_ids": list(range(51))})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_one_provider_failure_is_a_per_item_error_not_a_500(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, english="bicycle", translation_status="flagged")

        with patch(
            "src.db.services.translation_verify_service.verify_translation",
            new=AsyncMock(side_effect=RuntimeError("provider down")),
        ):
            resp = await ac.post("/api/triage/verify-translations", json={"card_ids": [card_id]})

        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["status"] == "error"
        assert "provider down" in item["error"]

    @pytest.mark.asyncio
    async def test_successful_check_returns_verdict(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, english="bicycle", translation_status="flagged")

        fake_result = {
            "status": "checked", "verdict": "likely_error", "reason": "not a bicycle",
            "input_tokens": 240, "output_tokens": 18,
        }
        with patch(
            "src.db.services.translation_verify_service.verify_translation",
            new=AsyncMock(return_value=fake_result),
        ):
            resp = await ac.post("/api/triage/verify-translations", json={"card_ids": [card_id]})

        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["verdict"] == "likely_error"
        assert item["reason"] == "not a bicycle"


# ---------------------------------------------------------------------------
# POST /triage/enrich-breakdowns
# ---------------------------------------------------------------------------

class TestEnrichBreakdownsBatch:
    @pytest.mark.asyncio
    async def test_no_gaps_card_is_skipped_without_writing_an_event(self, client):
        ac, factory = client
        breakdown = [{"thai": "น้ำ", "gloss": "water", "gloss_source": "card"}]
        card_id = await _seed_card(
            factory, thai="น้ำ", english="water",
            compound_breakdown=breakdown, is_compound=True,
        )

        resp = await ac.post("/api/triage/enrich-breakdowns", json={"card_ids": [card_id]})
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["status"] == "no_gaps"

        from src.db.models.card_correction_event import CardCorrectionEvent
        from sqlalchemy import func, select
        async with factory() as db:
            count = await db.scalar(select(func.count()).select_from(CardCorrectionEvent))
        assert count == 0

    @pytest.mark.asyncio
    async def test_low_confidence_fill_is_not_persisted_and_writes_no_event(self, client):
        """Regression test: apply_decision's llm_fill branch used to log an
        event (and report status='enriched') for a fill enrich_breakdown()
        itself declined to persist — the card was left unchanged while the
        UI claimed success. See NoCorrectionApplied in correction_service.py."""
        ac, factory = client
        breakdown = [{"thai": "น้ำ", "gloss": "water", "gloss_source": "card"}, {"thai": "แข็ง", "gloss": None}]
        card_id = await _seed_card(
            factory, thai="น้ำแข็ง", english="ice",
            compound_breakdown=breakdown, is_compound=True,
        )

        fake_result = {
            "status": "enriched", "parts": [breakdown[0], {"thai": "แข็ง", "gloss": "hard"}],
            "confidence": "low", "filled": ["แข็ง"], "persisted": False,
            "input_tokens": 200, "output_tokens": 20,
        }
        with patch(
            "src.db.services.compound_llm_service.enrich_breakdown",
            new=AsyncMock(return_value=fake_result),
        ):
            resp = await ac.post("/api/triage/enrich-breakdowns", json={"card_ids": [card_id]})

        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["status"] == "low_confidence"

        from src.db.models.card_correction_event import CardCorrectionEvent
        from sqlalchemy import func, select
        async with factory() as db:
            count = await db.scalar(select(func.count()).select_from(CardCorrectionEvent))
            card = await db.get(Card, card_id)
        assert count == 0
        assert card.compound_breakdown == json.dumps(breakdown, ensure_ascii=False)


# ---------------------------------------------------------------------------
# POST /triage/decisions
# ---------------------------------------------------------------------------

class TestSubmitDecisions:
    @pytest.mark.asyncio
    async def test_correct_decision_writes_override_and_returns_event(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, english="bicycle", translation_status="flagged")

        resp = await ac.post("/api/triage/decisions", json={
            "decisions": [
                {"card_id": card_id, "target": "translation", "action": "correct",
                 "payload": {"english": "train"}},
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["batch_id"] is None  # single-decision requests don't get a batch id
        assert len(data["events"]) == 1

        get_resp = await ac.get(f"/api/cards/{card_id}")
        assert get_resp.json()["english"] == "train"

    @pytest.mark.asyncio
    async def test_multi_decision_request_gets_one_batch_id(self, client):
        ac, factory = client
        card_a = await _seed_card(factory, thai="ก", english="a", translation_status="flagged")
        card_b = await _seed_card(factory, thai="ข", english="b", translation_status="flagged")

        resp = await ac.post("/api/triage/decisions", json={
            "decisions": [
                {"card_id": card_a, "target": "translation", "action": "keep"},
                {"card_id": card_b, "target": "translation", "action": "keep"},
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["batch_id"] is not None

        from sqlalchemy import select
        from src.db.models.card_correction_event import CardCorrectionEvent
        async with factory() as db:
            rows = (await db.execute(select(CardCorrectionEvent))).scalars().all()
            batch_ids = {r.batch_id for r in rows}
        assert batch_ids == {data["batch_id"]}

    @pytest.mark.asyncio
    async def test_invalid_decision_in_batch_writes_nothing(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, english="bicycle", translation_status="flagged")

        resp = await ac.post("/api/triage/decisions", json={
            "decisions": [
                {"card_id": card_id, "target": "translation", "action": "correct",
                 "payload": {"english": "train"}},
                {"card_id": 999999, "target": "translation", "action": "correct",
                 "payload": {"english": "x"}},
            ],
        })
        assert resp.status_code == 422

        from src.db.models.card_correction_event import CardCorrectionEvent
        from sqlalchemy import func, select
        async with factory() as db:
            count = await db.scalar(select(func.count()).select_from(CardCorrectionEvent))
        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_propagation_candidates(self, client):
        ac, factory = client
        card_a = await _seed_card(factory, thai="ไม่เป็นไร", english="bicycle", translation_status="flagged")
        card_b = await _seed_card(factory, thai="ไม่เป็นไร", english="bicycle", translation_status="flagged")

        resp = await ac.post("/api/triage/decisions", json={
            "decisions": [
                {"card_id": card_a, "target": "translation", "action": "correct",
                 "payload": {"english": "train"}},
            ],
        })
        data = resp.json()
        assert data["events"][0]["propagation_candidates"] == [card_b]


# ---------------------------------------------------------------------------
# POST /triage/undo
# ---------------------------------------------------------------------------

class TestUndo:
    @pytest.mark.asyncio
    async def test_undo_by_event_id_reflags_the_card(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, english="bicycle", translation_status="flagged")

        decision_resp = await ac.post("/api/triage/decisions", json={
            "decisions": [
                {"card_id": card_id, "target": "translation", "action": "correct",
                 "payload": {"english": "train"}},
            ],
        })
        event_id = decision_resp.json()["events"][0]["event_id"]

        undo_resp = await ac.post("/api/triage/undo", json={"event_id": event_id})
        assert undo_resp.status_code == 200
        assert undo_resp.json()["reverted"] == [event_id]

        get_resp = await ac.get(f"/api/cards/{card_id}")
        assert get_resp.json()["translation_status"] == "flagged"
        assert get_resp.json()["english"] == "bicycle"

    @pytest.mark.asyncio
    async def test_undo_requires_batch_id_or_event_id(self, client):
        ac, factory = client
        resp = await ac.post("/api/triage/undo", json={})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /corrections
# ---------------------------------------------------------------------------

class TestListCorrections:
    @pytest.mark.asyncio
    async def test_returns_newest_first_scoped_to_card(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, english="bicycle", translation_status="flagged")

        await ac.post("/api/triage/decisions", json={
            "decisions": [
                {"card_id": card_id, "target": "translation", "action": "correct",
                 "payload": {"english": "train"}},
            ],
        })

        resp = await ac.get("/api/corrections", params={"card_id": card_id})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["action"] == "correct"
        assert items[0]["to_value"] == {"english": "train"}
