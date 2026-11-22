"""
Tests for the manual card create/update routes' text-integrity guard
(src/api/routes/cards.py) — normalises thai/example_thai, and 422s naming
the code point when an invalid character survives normalisation (decision 9
in the text-integrity design doc: no silent repair on user input).

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_cards_text_integrity.py -v
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.api.deps import get_db
from src.db.models import Base, Deck


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


async def _make_deck(factory) -> int:
    async with factory() as db:
        deck = Deck(name="Test Deck")
        db.add(deck)
        await db.commit()
        return deck.id


class TestCreateCardValidation:
    @pytest.mark.asyncio
    async def test_pua_character_in_thai_returns_422_naming_code_point(self, client):
        ac, factory = client
        deck_id = await _make_deck(factory)

        resp = await ac.post(
            f"/api/decks/{deck_id}/cards",
            json={"thai": "กข", "english": "test"},
        )
        assert resp.status_code == 422
        assert "U+E000" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_clean_card_with_decomposed_sara_am_is_normalised(self, client):
        ac, factory = client
        deck_id = await _make_deck(factory)

        resp = await ac.post(
            f"/api/decks/{deck_id}/cards",
            json={"thai": "ดํา", "english": "black"},
        )
        assert resp.status_code == 201
        assert resp.json()["thai"] == "ดำ"


class TestUpdateCardValidation:
    @pytest.mark.asyncio
    async def test_pua_character_in_thai_update_returns_422(self, client):
        ac, factory = client
        deck_id = await _make_deck(factory)

        create_resp = await ac.post(
            f"/api/decks/{deck_id}/cards", json={"thai": "แมว", "english": "cat"}
        )
        card_id = create_resp.json()["id"]

        resp = await ac.patch(f"/api/cards/{card_id}", json={"thai": "กข"})
        assert resp.status_code == 422
        assert "U+E000" in resp.json()["detail"]
