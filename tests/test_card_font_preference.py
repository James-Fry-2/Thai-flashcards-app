"""Card-face font preference (brand/BRAND-SYSTEM.md §3): default, round trip, validation."""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.deps import get_db
from src.db.models import Base


@pytest_asyncio.fixture
async def ac():
    from src.main import app

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_card_font_defaults_to_looped_learner_font(ac):
    body = (await ac.get("/api/preferences/")).json()
    assert body["card_font"] == "learner"


@pytest.mark.asyncio
@pytest.mark.parametrize("font", ["classic", "realworld", "handwriting", "learner"])
async def test_card_font_round_trip(ac, font):
    body = (await ac.patch("/api/preferences/", json={"card_font": font})).json()
    assert body["card_font"] == font
    assert (await ac.get("/api/preferences/")).json()["card_font"] == font


@pytest.mark.asyncio
async def test_card_font_rejects_unknown_value(ac):
    resp = await ac.patch("/api/preferences/", json={"card_font": "comic-sans"})
    assert resp.status_code == 422
    assert (await ac.get("/api/preferences/")).json()["card_font"] == "learner"


@pytest.mark.asyncio
async def test_other_preferences_untouched_by_card_font_patch(ac):
    await ac.patch("/api/preferences/", json={"tts_default_speed": "slow"})
    body = (await ac.patch("/api/preferences/", json={"card_font": "realworld"})).json()
    assert body["tts_default_speed"] == "slow"
