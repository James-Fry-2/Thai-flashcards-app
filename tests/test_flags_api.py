"""
Tests for src/api/routes/flags.py — flag creation/listing/resolution and the
override PUT/DELETE endpoints, exercised through the real ASGI app.

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_flags_api.py -v
"""
import json

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base, Deck, Card
from src.db.models.card_schedule import CardSchedule
from src.db.models.review_log import ReviewLog
from src.db.models.card_flag import CardFlag
from src.db.models.card_override import CardOverride
from src.utils.compound import enumerate_segmentations
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


async def _seed_card(factory, thai="แมว", english="cat", compound_breakdown=None, is_compound=None):
    async with factory() as db:
        deck = Deck(name="Test Deck")
        db.add(deck)
        await db.flush()
        card = Card(
            deck_id=deck.id,
            thai=thai,
            english=english,
            card_type="vocab",
            compound_breakdown=json.dumps(compound_breakdown, ensure_ascii=False) if compound_breakdown else None,
            is_compound=is_compound,
        )
        db.add(card)
        await db.flush()
        db.add(CardSchedule(card_id=card.id, direction="th_to_en"))
        await db.commit()
        return card.id


# ---------------------------------------------------------------------------
# POST /cards/{id}/flags
# ---------------------------------------------------------------------------

class TestCreateFlag:
    @pytest.mark.asyncio
    async def test_snapshots_flagged_value_for_translation(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, english="cat")

        resp = await ac.post(f"/api/cards/{card_id}/flags", json={"target": "translation", "note": "looks wrong"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["target"] == "translation"
        assert data["status"] == "open"
        assert data["flagged_value"] == {"english": "cat"}
        assert data["note"] == "looks wrong"

    @pytest.mark.asyncio
    async def test_snapshot_reflects_an_existing_override(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, english="cat")

        put_resp = await ac.put(f"/api/cards/{card_id}/overrides/translation", json={"payload": {"english": "kitten"}})
        assert put_resp.status_code == 200

        resp = await ac.post(f"/api/cards/{card_id}/flags", json={"target": "translation"})
        assert resp.json()["flagged_value"] == {"english": "kitten"}

    @pytest.mark.asyncio
    async def test_second_post_same_open_flag_updates_not_duplicates(self, client):
        ac, factory = client
        card_id = await _seed_card(factory)

        r1 = await ac.post(f"/api/cards/{card_id}/flags", json={"target": "translation", "note": "first"})
        r2 = await ac.post(f"/api/cards/{card_id}/flags", json={"target": "translation", "note": "second"})
        assert r1.status_code == 201 and r2.status_code == 201
        assert r1.json()["id"] == r2.json()["id"]
        assert r2.json()["note"] == "second"

        async with factory() as db:
            count = await db.scalar(select(func.count()).select_from(CardFlag))
            assert count == 1

    @pytest.mark.asyncio
    async def test_invalid_target_returns_422(self, client):
        ac, factory = client
        card_id = await _seed_card(factory)
        resp = await ac.post(f"/api/cards/{card_id}/flags", json={"target": "not_a_real_target"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_unknown_card_returns_404(self, client):
        ac, factory = client
        resp = await ac.post("/api/cards/999999/flags", json={"target": "translation"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /flags, PATCH /flags/{id}
# ---------------------------------------------------------------------------

class TestListAndResolveFlags:
    @pytest.mark.asyncio
    async def test_list_includes_card_summary(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, thai="แมว", english="cat")
        await ac.post(f"/api/cards/{card_id}/flags", json={"target": "translation"})

        resp = await ac.get("/api/flags", params={"status": "open"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["card"]["thai"] == "แมว"
        assert items[0]["card"]["english"] == "cat"

    @pytest.mark.asyncio
    async def test_patch_status_sets_resolved_at(self, client):
        ac, factory = client
        card_id = await _seed_card(factory)
        flag_id = (await ac.post(f"/api/cards/{card_id}/flags", json={"target": "translation"})).json()["id"]

        resp = await ac.patch(f"/api/flags/{flag_id}", json={"status": "resolved"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "resolved"
        assert data["resolved_at"] is not None

        list_resp = await ac.get("/api/flags", params={"status": "open"})
        assert list_resp.json()["items"] == []


# ---------------------------------------------------------------------------
# PUT/DELETE /cards/{id}/overrides/{target}
# ---------------------------------------------------------------------------

class TestOverrideRoundtrip:
    @pytest.mark.asyncio
    async def test_translation_override_then_revert(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, english="cat")

        put_resp = await ac.put(f"/api/cards/{card_id}/overrides/translation", json={"payload": {"english": "kitten"}})
        assert put_resp.status_code == 200

        get_resp = await ac.get(f"/api/cards/{card_id}")
        assert get_resp.json()["english"] == "kitten"
        assert get_resp.json()["english_source"] == "user"

        del_resp = await ac.delete(f"/api/cards/{card_id}/overrides/translation")
        assert del_resp.status_code == 204

        get_resp2 = await ac.get(f"/api/cards/{card_id}")
        assert get_resp2.json()["english"] == "cat"
        assert get_resp2.json().get("english_source") is None

    @pytest.mark.asyncio
    async def test_translation_override_empty_english_422(self, client):
        ac, factory = client
        card_id = await _seed_card(factory)
        resp = await ac.put(f"/api/cards/{card_id}/overrides/translation", json={"payload": {"english": "  "}})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_compound_suppressed_override(self, client):
        ac, factory = client
        breakdown = [
            {"thai": "น้ำ", "romanization": "naam", "gloss": "water", "gloss_source": "card"},
            {"thai": "แข็ง", "romanization": "khaeng", "gloss": "hard", "gloss_source": "lexicon"},
        ]
        card_id = await _seed_card(factory, thai="น้ำแข็ง", english="ice", compound_breakdown=breakdown, is_compound=True)

        resp = await ac.put(f"/api/cards/{card_id}/overrides/compound", json={"payload": {"suppressed": True}})
        assert resp.status_code == 200

        get_resp = await ac.get(f"/api/cards/{card_id}")
        data = get_resp.json()
        assert data["compound_breakdown"] is None
        assert data["compound_suppressed"] is True
        assert data["is_compound"] is True  # structural fact, untouched by suppression

    @pytest.mark.asyncio
    async def test_compound_parts_override_must_match_a_real_segmentation(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, thai="น้ำแข็ง", english="ice")

        bogus_parts = [{"thai": "abc", "romanization": None, "gloss": None, "gloss_source": None}]
        resp = await ac.put(f"/api/cards/{card_id}/overrides/compound", json={"payload": {"parts": bogus_parts}})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_compound_parts_override_accepts_a_valid_segmentation(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, thai="น้ำแข็ง", english="ice")

        segmentations = enumerate_segmentations("น้ำแข็ง", limit=8)
        assert segmentations, "expected at least one valid segmentation for น้ำแข็ง"
        chosen = segmentations[0]
        parts = [{"thai": t, "romanization": None, "gloss": None, "gloss_source": None} for t in chosen]

        resp = await ac.put(f"/api/cards/{card_id}/overrides/compound", json={"payload": {"parts": parts}})
        assert resp.status_code == 200

        get_resp = await ac.get(f"/api/cards/{card_id}")
        data = get_resp.json()
        assert [p["thai"] for p in data["compound_breakdown"]] == chosen
        assert data["compound_breakdown_source"] == "user"

    @pytest.mark.asyncio
    async def test_invalid_override_target_422(self, client):
        ac, factory = client
        card_id = await _seed_card(factory)
        resp = await ac.put(f"/api/cards/{card_id}/overrides/romanization", json={"payload": {"value": "x"}})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Candidate endpoints
# ---------------------------------------------------------------------------

class TestCandidateEndpoints:
    @pytest.mark.asyncio
    async def test_compound_candidates_include_current_segmentation(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, thai="น้ำแข็ง", english="ice")

        resp = await ac.get(f"/api/cards/{card_id}/compound-candidates")
        assert resp.status_code == 200
        data = resp.json()
        assert any(seg["parts"] == ["น้ำ", "แข็ง"] for seg in data["segmentations"])
        assert data["allow_free_text_gloss"] is True
        assert "น้ำ" in data["part_glosses"]

    @pytest.mark.asyncio
    async def test_translation_candidates_empty_allows_free_text(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, thai="ฯฯฯไม่มีจริงฯฯฯ", english="nonsense")

        resp = await ac.get(f"/api/cards/{card_id}/translation-candidates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["candidates"] == []
        assert data["allow_free_text"] is True


# ---------------------------------------------------------------------------
# Acceptance: flags/overrides never touch FSRS tables or the card row itself
# ---------------------------------------------------------------------------

class TestScopeIsolation:
    @pytest.mark.asyncio
    async def test_flagging_and_overriding_never_touches_schedule_or_review_log(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, english="cat")

        async def _counts():
            async with factory() as db:
                sched = (await db.execute(select(func.count()).select_from(CardSchedule))).scalar()
                log = (await db.execute(select(func.count()).select_from(ReviewLog))).scalar()
                return sched, log

        before = await _counts()

        await ac.post(f"/api/cards/{card_id}/flags", json={"target": "translation", "note": "hmm"})
        await ac.put(f"/api/cards/{card_id}/overrides/translation", json={"payload": {"english": "kitten"}})
        await ac.delete(f"/api/cards/{card_id}/overrides/translation")

        after = await _counts()
        assert after == before

    @pytest.mark.asyncio
    async def test_translation_override_leaves_card_row_english_unmodified(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, english="cat")

        await ac.put(f"/api/cards/{card_id}/overrides/translation", json={"payload": {"english": "kitten"}})

        async with factory() as db:
            card = await db.get(Card, card_id)
            assert card.english == "cat"

    @pytest.mark.asyncio
    async def test_resolve_translation_correct_leaves_card_row_unmodified(self, client):
        ac, factory = client
        card_id = await _seed_card(factory, english="bicycle")

        resp = await ac.post(f"/api/cards/{card_id}/resolve-translation", json={"action": "correct", "english": "train"})
        assert resp.status_code == 200
        assert resp.json()["english"] == "train"
        assert resp.json()["translation_status"] == "confirmed"

        async with factory() as db:
            card = await db.get(Card, card_id)
            assert card.english == "bicycle"  # material value untouched

            override = await db.scalar(select(CardOverride).where(CardOverride.card_id == card_id))
            assert override is not None
            assert json.loads(override.payload) == {"english": "train", "from_candidate": False}


# ---------------------------------------------------------------------------
# Overrides are batched, not N+1, on list endpoints
# ---------------------------------------------------------------------------

class TestOverridesAreBatched:
    @pytest.mark.asyncio
    async def test_list_50_cards_issues_one_override_query_not_fifty(self):
        from sqlalchemy import event
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

        async with factory() as db:
            deck = Deck(name="Big Deck")
            db.add(deck)
            await db.flush()
            for i in range(50):
                db.add(Card(deck_id=deck.id, thai=f"คำ{i}", english=f"word{i}", card_type="vocab"))
            await db.commit()
            deck_id = deck.id

        query_count = 0

        def _count_override_queries(conn, cursor, statement, parameters, context, executemany):
            nonlocal query_count
            if "card_override" in statement:
                query_count += 1

        sync_engine = engine.sync_engine
        event.listen(sync_engine, "before_cursor_execute", _count_override_queries)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get(f"/api/decks/{deck_id}/cards", params={"limit": 50})
        finally:
            event.remove(sync_engine, "before_cursor_execute", _count_override_queries)
            app.dependency_overrides.clear()
            await engine.dispose()

        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 50
        assert query_count == 1, f"expected exactly 1 card_override query for a 50-card list, got {query_count}"
