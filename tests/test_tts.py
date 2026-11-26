"""
Tests for cached text-to-speech: src/db/services/tts_service.py, the Azure
SSML builder and the /tts, /cards/{id}/audio, /reading/texts/.../audio routes.
Azure is replaced by a fake provider, so no API calls are made.

    pytest tests/test_tts.py -v
"""
import json

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.deps import get_db
from src.config.settings import get_settings
from src.db.models import Base, Card, CardMedia, Deck, GeneratedText, TTSUsage
from src.db.services import tts_service
from src.tts import TTSError, TTSNotConfigured
from src.tts.azure_provider import build_ssml


class FakeTTS:
    name = "fake"

    def __init__(self):
        self.calls = []
        self.fail = None

    async def synthesize(self, text, voice, rate):
        self.calls.append((text, voice, rate))
        if self.fail:
            raise self.fail
        return b"ID3" + f"{voice}|{rate}|{text}".encode()


@pytest.fixture
def fake_tts(monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))
    fake = FakeTTS()
    monkeypatch.setattr(tts_service, "get_tts_provider", lambda s=None: fake)
    return fake


@pytest_asyncio.fixture
async def client():
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac, factory
    app.dependency_overrides.clear()
    await engine.dispose()


async def _usage_count(factory):
    async with factory() as db:
        return await db.scalar(select(func.count(TTSUsage.id)))


# ---------------------------------------------------------------------------
# unit
# ---------------------------------------------------------------------------

def test_clean_text_normalises_and_rejects_bad_input():
    assert tts_service.clean_text("  สวัสดี​  ครับ ") == "สวัสดี ครับ"
    for bad in ["", "   ", "hello", "สวัส�ดี", "ก" * 501]:
        with pytest.raises(tts_service.InvalidTTSText):
            tts_service.clean_text(bad)


def test_ssml_escapes_text_and_applies_rate():
    ssml = build_ssml("a < b & 'c'", "th-TH-PremwadeeNeural", "-30%")
    assert "a &lt; b &amp; 'c'" in ssml
    assert "<prosody rate=\"-30%\">" in ssml
    assert "name=\"th-TH-PremwadeeNeural\"" in ssml
    assert "prosody" not in build_ssml("สวัสดี", "v", "0%")


def test_dialogue_voices_from_particles():
    lines = [
        {"speaker": "นิด", "thai": "กินข้าวหรือยังคะ"},
        {"speaker": "ต้น", "thai": "ยังครับ"},
        {"speaker": "นิด", "thai": "ไปกันค่ะ"},
    ]
    assert tts_service.dialogue_voices(lines) == {"นิด": "female", "ต้น": "male"}


def test_dialogue_voices_keeps_unmarked_speakers_distinct():
    lines = [{"speaker": "A", "thai": "ไปไหน"}, {"speaker": "B", "thai": "ไปตลาด"}]
    voices = tts_service.dialogue_voices(lines)
    assert set(voices.values()) == {"female", "male"}
    # one marked speaker: the other gets the remaining voice
    lines = [{"speaker": "A", "thai": "ไปไหน"}, {"speaker": "B", "thai": "ไปตลาดค่ะ"}]
    assert tts_service.dialogue_voices(lines) == {"A": "male", "B": "female"}


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_speak_caches_and_records_usage_once(client, fake_tts):
    ac, factory = client
    r1 = await ac.post("/api/tts", json={"text": "สวัสดีครับ"})
    assert r1.status_code == 200
    assert r1.headers["content-type"] == "audio/mpeg"
    assert r1.headers["x-tts-cache"] == "miss"
    r2 = await ac.post("/api/tts", json={"text": " สวัสดีครับ​"})  # same text after normalising
    assert r2.headers["x-tts-cache"] == "hit"
    assert r2.content == r1.content
    assert len(fake_tts.calls) == 1
    assert await _usage_count(factory) == 1


@pytest.mark.asyncio
async def test_speed_and_voice_are_separate_cache_entries(client, fake_tts):
    ac, _ = client
    settings = get_settings()
    await ac.post("/api/tts", json={"text": "น้ำ"})
    await ac.post("/api/tts", json={"text": "น้ำ", "speed": "slow"})
    await ac.post("/api/tts", json={"text": "น้ำ", "voice": "male"})
    assert [(v, r) for _, v, r in fake_tts.calls] == [
        (settings.tts_voice_female, "0%"),
        (settings.tts_voice_female, settings.tts_slow_rate),
        (settings.tts_voice_male, "0%"),
    ]


@pytest.mark.asyncio
async def test_invalid_text_never_reaches_provider(client, fake_tts):
    ac, factory = client
    r = await ac.post("/api/tts", json={"text": "สวัส�ดี"})
    assert r.status_code == 422
    assert fake_tts.calls == []
    assert await _usage_count(factory) == 0


@pytest.mark.asyncio
async def test_not_configured_and_provider_errors(client, fake_tts, monkeypatch):
    ac, factory = client

    def not_configured(s=None):
        raise TTSNotConfigured("no key")

    monkeypatch.setattr(tts_service, "get_tts_provider", not_configured)
    r = await ac.post("/api/tts", json={"text": "ไก่"})
    assert r.status_code == 503 and r.json()["detail"] == "tts_not_configured"

    monkeypatch.setattr(tts_service, "get_tts_provider", lambda s=None: fake_tts)
    fake_tts.fail = TTSError("boom")
    r = await ac.post("/api/tts", json={"text": "ไก่"})
    assert r.status_code == 502
    assert await _usage_count(factory) == 0

    fake_tts.fail = None  # a failure leaves nothing cached
    r = await ac.post("/api/tts", json={"text": "ไก่"})
    assert r.status_code == 200 and r.headers["x-tts-cache"] == "miss"


@pytest.mark.asyncio
async def test_card_audio_records_media_once(client, fake_tts):
    ac, factory = client
    async with factory() as db:
        deck = Deck(name="d")
        db.add(deck)
        await db.flush()
        card = Card(deck_id=deck.id, thai="ข้าว", english="rice", card_type="vocab",
                    example_thai="กินข้าวหรือยัง", example_english="Have you eaten?")
        bare = Card(deck_id=deck.id, thai="น้ำ", english="water", card_type="vocab")
        db.add_all([card, bare])
        await db.commit()
        card_id, bare_id = card.id, bare.id

    for _ in range(2):
        assert (await ac.get(f"/api/cards/{card_id}/audio")).status_code == 200
    assert (await ac.get(f"/api/cards/{card_id}/audio?field=example&speed=slow")).status_code == 200
    assert [t for t, _, _ in fake_tts.calls] == ["ข้าว", "กินข้าวหรือยัง"]

    async with factory() as db:
        media = (await db.scalars(select(CardMedia).where(CardMedia.card_id == card_id))).all()
    assert sorted(m.alt_text for m in media) == ["example:slow", "thai:normal"]
    assert all(m.media_type == "audio" and m.storage_path.startswith("tts/") for m in media)

    assert (await ac.get(f"/api/cards/{bare_id}/audio?field=example")).status_code == 422
    assert (await ac.get("/api/cards/99999/audio")).status_code == 404


@pytest.mark.asyncio
async def test_reading_line_uses_speaker_voice(client, fake_tts):
    ac, factory = client
    settings = get_settings()
    lines = [
        {"speaker": "นิด", "word": "", "thai": "กินข้าวหรือยังคะ", "english": "Eaten yet?"},
        {"speaker": "ต้น", "word": "", "thai": "ยังครับ", "english": "Not yet."},
    ]
    async with factory() as db:
        text = GeneratedText(user_id=1, kind="dialogue", scope="topic", scope_id=1, title="t",
                             lines=json.dumps(lines, ensure_ascii=False), target_words="[]")
        other = GeneratedText(user_id=2, kind="dialogue", scope="topic", scope_id=1, title="t",
                              lines=json.dumps(lines, ensure_ascii=False), target_words="[]")
        db.add_all([text, other])
        await db.commit()
        text_id, other_id = text.id, other.id

    assert (await ac.get(f"/api/reading/texts/{text_id}/lines/0/audio")).status_code == 200
    assert (await ac.get(f"/api/reading/texts/{text_id}/lines/1/audio")).status_code == 200
    assert [v for _, v, _ in fake_tts.calls] == [settings.tts_voice_female, settings.tts_voice_male]
    assert (await ac.get(f"/api/reading/texts/{text_id}/lines/5/audio")).status_code == 404
    assert (await ac.get(f"/api/reading/texts/{other_id}/lines/0/audio")).status_code == 404


@pytest.mark.asyncio
async def test_status_reports_usage(client, fake_tts):
    ac, _ = client
    await ac.post("/api/tts", json={"text": "สวัสดี"})
    body = (await ac.get("/api/tts/status")).json()
    assert body["usage"]["total_chars"] == len("สวัสดี")
    assert body["usage"]["calls"] == 1
    assert "configured" in body


@pytest.mark.asyncio
async def test_audio_preferences_round_trip(client):
    ac, _ = client
    body = (await ac.get("/api/preferences/")).json()
    assert body["tts_autoplay_on_reveal"] is False and body["tts_default_speed"] == "normal"
    body = (await ac.patch("/api/preferences/", json={"tts_autoplay_on_reveal": True, "tts_default_speed": "slow"})).json()
    assert body["tts_autoplay_on_reveal"] is True and body["tts_default_speed"] == "slow"
    assert (await ac.patch("/api/preferences/", json={"tts_default_speed": "fast"})).status_code == 422
