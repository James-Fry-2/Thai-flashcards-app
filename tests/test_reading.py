"""
Tests for Read & mine mode: src/db/services/reading_service.py and
src/api/routes/reading.py.

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_reading.py -v
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.deps import get_db
from src.db.models import Base, Deck, Card, Upload, UploadPage
from src.db.models.card_schedule import CardSchedule
from src.db.services import reading_service as rs

PAGE_TEXT = "สวัสดีครับ คุณสบายดีไหม\nHello, how are you?\nผมชอบกินกล้วย"


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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac, factory
    app.dependency_overrides.clear()
    await engine.dispose()


async def _seed(factory, cards: dict[str, tuple[str, float | None]]):
    """cards: {thai: (fsrs_state, stability)}. Returns (deck_id, upload_id)."""
    async with factory() as db:
        deck = Deck(name="Book deck")
        db.add(deck)
        await db.flush()
        upload = Upload(filename="ch1.pdf", file_type="pdf", kind="single", deck_id=deck.id,
                        status="done", chapter_label="Chapter 1")
        db.add(upload)
        await db.flush()
        db.add(UploadPage(upload_id=upload.id, page_index=0, status="done", text=PAGE_TEXT))
        db.add(UploadPage(upload_id=upload.id, page_index=1, status="done", text="กล้วย"))
        for i, (thai, (state, stability)) in enumerate(cards.items()):
            card = Card(deck_id=deck.id, thai=thai, english=f"w{i}", card_type="vocab")
            db.add(card)
            await db.flush()
            db.add(CardSchedule(card_id=card.id, direction="th_to_en", fsrs_state=state, fsrs_stability=stability))
        await db.commit()
        return deck.id, upload.id


def _words(lines):
    return {seg["text"]: seg.get("status") for line in lines for seg in line if seg.get("status")}


# ---------------------------------------------------------------------------
# unit
# ---------------------------------------------------------------------------

def test_segments_concatenate_back_to_the_line():
    index = rs.WordIndex()
    for line in PAGE_TEXT.split("\n"):
        segs = rs.segment_line(line, index)
        assert "".join(s["text"] for s in segs) == line


def test_english_and_punctuation_get_no_status():
    segs = rs.segment_line("Hello, 123 ๆ", rs.WordIndex())
    assert all("status" not in s for s in segs)


def test_phrase_cards_match_across_tokens():
    index = rs.WordIndex(status={"สบายดี": "known"}, card_id={"สบายดี": 7})
    index.max_tokens_by_first = {t: 2 for t in rs.tokenize_line("สบายดี") if t.strip()}
    segs = rs.segment_line("คุณสบายดีไหม", index)
    assert {"text": "สบายดี", "status": "known", "card_id": 7} in segs


def test_score_counts_occurrences():
    lines = [[{"text": "ก", "status": "known"}, {"text": " "}, {"text": "ข", "status": "unknown"},
              {"text": "ข", "status": "unknown"}]]
    s = rs.score(lines)
    assert s["thai_words"] == 3 and s["known_pct"] == 33 and s["unknown_unique"] == 1


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_page_statuses_follow_card_stability(client):
    ac, factory = client
    _, upload_id = await _seed(factory, {
        "สวัสดี": ("review", 40.0),   # solid -> known
        "กล้วย": ("review", 3.0),     # studied, not solid -> learning
        "ชอบ": ("new", None),         # in deck, not studied
    })
    r = await ac.get(f"/api/reading/uploads/{upload_id}/pages/0")
    assert r.status_code == 200
    body = r.json()
    words = _words(body["lines"])
    assert words["สวัสดี"] == "known"
    assert words["กล้วย"] == "learning"
    assert words["ชอบ"] == "new"
    assert words.get("ครับ") == "unknown"
    assert body["page_count"] == 2 and body["next_page"] == 1 and body["prev_page"] is None
    assert body["stats"]["counts"]["known"] == 1


@pytest.mark.asyncio
async def test_list_reports_uploads_with_scores(client):
    ac, factory = client
    _, upload_id = await _seed(factory, {"สวัสดี": ("review", 40.0)})
    r = await ac.get("/api/reading/uploads")
    [item] = r.json()
    assert item["upload_id"] == upload_id and item["title"] == "Chapter 1"
    assert item["pages"] == 2 and item["counts"]["known"] == 1


@pytest.mark.asyncio
async def test_mark_known_changes_status_and_can_be_undone(client):
    ac, factory = client
    _, upload_id = await _seed(factory, {})
    await ac.post("/api/reading/known", json={"thai": "ครับ"})
    words = _words((await ac.get(f"/api/reading/uploads/{upload_id}/pages/0")).json()["lines"])
    assert words["ครับ"] == "known"

    await ac.post("/api/reading/known", json={"thai": "ครับ", "known": False})
    words = _words((await ac.get(f"/api/reading/uploads/{upload_id}/pages/0")).json()["lines"])
    assert words["ครับ"] == "unknown"


@pytest.mark.asyncio
async def test_add_card_goes_to_upload_deck_first_in_new_queue(client):
    ac, factory = client
    deck_id, upload_id = await _seed(factory, {"ชอบ": ("new", None)})
    r = await ac.post("/api/reading/cards", json={
        "thai": "ครับ", "english": "polite particle", "upload_id": upload_id,
        "example_thai": "สวัสดีครับ คุณสบายดีไหม",
    })
    assert r.status_code == 201 and r.json()["created"] is True and r.json()["deck_id"] == deck_id

    async with factory() as db:
        card = await db.get(Card, r.json()["card_id"])
        assert card.example_thai == "สวัสดีครับ คุณสบายดีไหม"
        assert card.source_upload_id == upload_id
        sched = await db.scalar(select(CardSchedule).where(CardSchedule.card_id == card.id))
        assert sched.fsrs_state == "new"

    # Daily limit of 1 new card: the mined card is the one introduced.
    await ac.patch("/api/preferences/", json={"daily_new_limit": 1})
    session = (await ac.post(f"/api/review/session?deck_id={deck_id}")).json()
    assert [c["thai"] for c in session["cards"]] == ["ครับ"]

    # Adding the same word again doesn't duplicate it.
    r = await ac.post("/api/reading/cards", json={"thai": "ครับ", "english": "x", "upload_id": upload_id})
    assert r.json()["created"] is False


@pytest.mark.asyncio
async def test_add_card_without_upload_deck_uses_reading_deck(client):
    ac, _ = client
    r = await ac.post("/api/reading/cards", json={"thai": "แมว", "english": "cat"})
    assert r.status_code == 201
    deck = (await ac.get(f"/api/decks/{r.json()['deck_id']}")).json()
    assert deck["name"] == rs.READING_DECK_NAME


@pytest.mark.asyncio
async def test_lookup_returns_glosses_and_existing_card(client, monkeypatch):
    ac, factory = client
    await _seed(factory, {"กล้วย": ("review", 3.0)})

    async def fake_candidates(db, thai):
        return [{"gloss": "banana", "source": "volubilis"}]
    monkeypatch.setattr("src.utils.compound.gloss_candidates", fake_candidates)

    body = (await ac.get("/api/reading/lookup", params={"thai": "กล้วย"})).json()
    assert body["glosses"] == [{"gloss": "banana", "source": "volubilis"}]
    assert body["card"]["english"] == "w0"
    assert body["romanization"]


@pytest.mark.asyncio
async def test_rejects_non_thai_and_missing_pages(client):
    ac, factory = client
    _, upload_id = await _seed(factory, {})
    assert (await ac.post("/api/reading/known", json={"thai": "hello"})).status_code == 422
    assert (await ac.get(f"/api/reading/uploads/{upload_id}/pages/99")).status_code == 404


def test_tokens_kept_whole_are_split_into_known_words():
    index = rs.WordIndex(status={"กิน": "learning", "ข้าว": "known"})
    words = {s["text"]: s["status"] for s in rs.segment_line("กินข้าว", index) if "status" in s}
    assert words == {"กิน": "learning", "ข้าว": "known"}
    # no full split -> stays one unknown word
    assert rs.split_into_known("กินปลา", rs.WordIndex(status={"กิน": "known"})) is None
