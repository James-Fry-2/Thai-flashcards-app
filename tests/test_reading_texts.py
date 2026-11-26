"""
Tests for generated reading texts: src/db/services/reading_text_service.py
and the /reading/texts + /reading/sources routes. Claude is replaced by a
fake provider, so no API calls are made.

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_reading_texts.py -v
"""
import json
import random

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.deps import get_db
from src.db.models import Base, Deck, Card, Topic, CardTopic, Upload
from src.db.models.card_schedule import CardSchedule
from src.db.services import reading_text_service as rts
from src.db.services import reading_service as rs
from src.llm.base import LLMResponse, LLMRefusal
from src.llm.registry import LLMTask

WORDS = {  # thai: (english, state, stability)
    "กิน": ("eat", "review", 2.0),       # learning
    "ข้าว": ("rice", "review", 40.0),    # known
    "น้ำ": ("water", "new", None),       # new
    "ร้านอาหาร": ("restaurant", "learning", 0.5),
    "อร่อย": ("delicious", "new", None),
}

DIALOGUE = {
    "title": "At lunch",
    "lines": [
        {"speaker": "นิด", "word": "", "thai": "คุณกินข้าวหรือยังคะ", "english": "Have you eaten yet?"},
        {"speaker": "ต้น", "word": "", "thai": "ยังครับ ไปร้านอาหารกันไหม", "english": "Not yet. Shall we go to a restaurant?"},
        {"speaker": "นิด", "word": "", "thai": "ได้ค่ะ ร้านนี้อร่อยมาก", "english": "Sure. This place is really good."},
        {"speaker": "ต้น", "word": "", "thai": "ขอน้ำเปล่าครับ", "english": "Plain water, please."},
        {"speaker": "ต้น", "word": "", "thai": "", "english": "dropped: no thai"},
    ],
}


OK_CHECK = {"overall": {"natural": True, "problem": ""}, "rewrite": [], "lines": []}


class FakeProvider:
    def __init__(self, task, state):
        self.task, self.state = task, state

    async def complete(self, messages, **kwargs):
        st = self.state
        st["calls"].append((self.task, messages[-1].content, kwargs))
        if st["refuse"]:
            raise LLMRefusal("no")
        if self.task == LLMTask.READING_GENERATION:
            body = st["gen"].pop(0) if st["gen"] else DIALOGUE
        else:
            if st["fail_check"]:
                raise RuntimeError("check down")
            body = st["check"] or OK_CHECK
        return LLMResponse(text=json.dumps(body, ensure_ascii=False), input_tokens=1000, output_tokens=500,
                           model="claude-opus-5-5")


@pytest.fixture
def fake_llm(monkeypatch):
    state = {"calls": [], "check": None, "fail_check": False, "refuse": False, "gen": []}

    def get_provider(task):
        return FakeProvider(task, state)

    monkeypatch.setattr(rts, "get_provider", get_provider)
    return state


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


async def _seed(factory, words=WORDS):
    async with factory() as db:
        deck = Deck(name="Food")
        db.add(deck)
        await db.flush()
        upload = Upload(filename="food.pdf", file_type="pdf", kind="single", deck_id=deck.id,
                        status="done", chapter_label="Food chapter")
        topic = Topic(name="Food")
        db.add_all([upload, topic])
        await db.flush()
        for thai, (english, state, stability) in words.items():
            card = Card(deck_id=deck.id, thai=thai, english=english, card_type="vocab", source_upload_id=upload.id)
            db.add(card)
            await db.flush()
            db.add(CardSchedule(card_id=card.id, direction="th_to_en", fsrs_state=state, fsrs_stability=stability))
            db.add(CardTopic(card_id=card.id, topic_id=topic.id))
        grammar = Card(deck_id=deck.id, thai="ไม่...เลย", english="not at all", card_type="grammar",
                       source_upload_id=upload.id)
        db.add(grammar)
        await db.commit()
        return topic.id, upload.id


# ---------------------------------------------------------------------------
# unit
# ---------------------------------------------------------------------------

def test_pick_candidates_prefers_learning_then_known_and_caps_unstudied():
    cards = [Card(thai=t, english=e, card_type="vocab") for t, (e, _, _) in WORDS.items()]
    cards += [Card(thai=f"คำ{i}", english=f"w{i}", card_type="vocab") for i in range(6)]  # unstudied
    index = rs.WordIndex(status={"กิน": "learning", "ร้านอาหาร": "learning", "ข้าว": "known"})
    picked = rts.pick_candidates(cards, index, random.Random(1), n=12, max_new=2)
    assert {c["thai"] for c in picked[:2]} == {"กิน", "ร้านอาหาร"}
    assert picked[2]["thai"] == "ข้าว"  # known before unstudied
    assert sum(c["status"] == "new" for c in picked) == 2


def test_hard_words_ignores_known_practice_and_common_words():
    index = rs.WordIndex(status={"กิน": "known"})
    lines = [{"thai": "กินข้าวที่บ้าน ฟูกเป่าลม"}]
    hard = rts.hard_words(lines, index, practice={"ข้าว"})
    assert "ที่" not in hard and "บ้าน" not in hard  # very common
    assert "กิน" not in hard and "ข้าว" not in hard
    assert any("ฟูก" in w for w in hard)


def test_apply_check_fixes_lines_and_records_notes():
    lines = [{"speaker": "a", "word": "", "thai": "กินข้าว", "english": "eat rice"},
             {"speaker": "b", "word": "", "thai": "ดีครับ", "english": "good"}]
    out, check = rts.apply_check(lines, {**OK_CHECK, "lines": [
        {"index": 0, "verdict": "ok", "thai": "กินข้าว", "english": "eat rice", "note": ""},
        {"index": 1, "verdict": "fixed", "thai": "ดีค่ะ", "english": "Good.", "note": "Speaker is female."},
        {"index": 9, "verdict": "fixed", "thai": "x", "english": "x", "note": "out of range"},
    ]})
    assert out[1]["thai"] == "ดีค่ะ" and out[1]["fixed"] is True and "fixed" not in out[0]
    assert check["fixed"] == 1 and check["rewritten"] is False
    assert check["notes"] == [{"index": 1, "note": "Speaker is female."}]


def test_apply_check_whole_text_rewrite_replaces_lines():
    lines = [{"speaker": "a", "word": "", "thai": "กิน", "english": "eat"}] * 3
    rewrite = [{"speaker": "นิด", "word": "", "thai": t, "english": "x"} for t in ("กินข้าวไหม", "กินแล้ว", "ดีค่ะ")]
    out, check = rts.apply_check(lines, {"overall": {"natural": False, "problem": "Jumps topic."},
                                         "rewrite": rewrite, "lines": []})
    assert [l["thai"] for l in out] == ["กินข้าวไหม", "กินแล้ว", "ดีค่ะ"]
    assert check["rewritten"] is True and check["problem"] == "Jumps topic."


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_dialogue_checks_and_renders(client, fake_llm):
    ac, factory = client
    topic_id, _ = await _seed(factory)
    fake_llm["check"] = {**OK_CHECK, "lines": [
        {"index": 1, "verdict": "fixed", "thai": "ยังครับ ไปร้านอาหารด้วยกันไหม",
         "english": "Not yet. Want to go to a restaurant together?", "note": "More natural."},
    ]}

    r = await ac.post("/api/reading/texts", json={"kind": "dialogue", "topic_id": topic_id})
    assert r.status_code == 201, r.text
    text = (await ac.get(f"/api/reading/texts/{r.json()['id']}")).json()

    assert text["title"] == "At lunch" and text["scope_label"] == "Food"
    assert len(text["lines"]) == 4  # the empty-thai line was dropped
    assert text["lines"][1]["thai"] == "ยังครับ ไปร้านอาหารด้วยกันไหม" and text["lines"][1]["fixed"]
    assert text["check"]["checked"] and text["check"]["fixed"] == 1
    # targets are the candidates actually used; grammar-pattern cards never are
    assert "ไม่...เลย" not in text["target_words"]
    assert set(text["target_words"]) == {"กิน", "ข้าว", "น้ำ", "ร้านอาหาร", "อร่อย"}
    # words are coloured like the reader
    statuses = {s["text"]: s.get("status") for l in text["lines"] for s in l["segments"]}
    assert statuses["ข้าว"] == "known" and statuses["อร่อย"] == "new"

    # every line carries romanization in the preferred scheme (Paiboon+ by default)
    assert all(l["romanization"] for l in text["lines"])
    assert text["lines"][0]["romanization"].startswith("kun")

    gen_call = fake_llm["calls"][0]
    assert gen_call[0] == LLMTask.READING_GENERATION and "json_schema" in gen_call[2]
    assert "กิน (eat)" in gen_call[1]
    assert fake_llm["calls"][1][0] == LLMTask.READING_CHECK


@pytest.mark.asyncio
async def test_failed_check_still_saves_text_unchecked(client, fake_llm):
    ac, factory = client
    _, upload_id = await _seed(factory)
    fake_llm["fail_check"] = True
    r = await ac.post("/api/reading/texts", json={"kind": "sentences", "upload_id": upload_id})
    assert r.status_code == 201
    [item] = (await ac.get("/api/reading/texts")).json()
    assert item["checked"] is False and item["kind"] == "sentences" and item["scope_label"] == "Food chapter"


@pytest.mark.asyncio
async def test_too_few_cards_is_a_clear_error(client, fake_llm):
    ac, factory = client
    topic_id, _ = await _seed(factory, {"กิน": ("eat", "new", None), "น้ำ": ("water", "new", None)})
    r = await ac.post("/api/reading/texts", json={"kind": "dialogue", "topic_id": topic_id})
    assert r.status_code == 422 and "at least 3" in r.json()["detail"]
    assert fake_llm["calls"] == []


@pytest.mark.asyncio
async def test_refusal_and_bad_requests(client, fake_llm):
    ac, factory = client
    topic_id, _ = await _seed(factory)
    fake_llm["refuse"] = True
    assert (await ac.post("/api/reading/texts", json={"kind": "dialogue", "topic_id": topic_id})).status_code == 502
    assert (await ac.post("/api/reading/texts", json={"kind": "poem", "topic_id": topic_id})).status_code == 422
    assert (await ac.post("/api/reading/texts", json={"kind": "dialogue"})).status_code == 422
    assert (await ac.post("/api/reading/texts", json={"kind": "dialogue", "topic_id": 999})).status_code == 404


@pytest.mark.asyncio
async def test_sources_and_delete(client, fake_llm):
    ac, factory = client
    topic_id, upload_id = await _seed(factory)
    sources = (await ac.get("/api/reading/sources")).json()
    assert sources["topics"] == [{"id": topic_id, "name": "Food", "card_count": 5}]
    assert sources["chapters"][0]["upload_id"] == upload_id

    text_id = (await ac.post("/api/reading/texts", json={"kind": "dialogue", "topic_id": topic_id})).json()["id"]
    assert (await ac.delete(f"/api/reading/texts/{text_id}")).status_code == 204
    assert (await ac.get(f"/api/reading/texts/{text_id}")).status_code == 404


@pytest.mark.asyncio
async def test_romanization_follows_settings(client, fake_llm):
    ac, factory = client
    topic_id, _ = await _seed(factory)
    text_id = (await ac.post("/api/reading/texts", json={"kind": "dialogue", "topic_id": topic_id})).json()["id"]
    paiboon = (await ac.get(f"/api/reading/texts/{text_id}")).json()["lines"][0]["romanization"]
    await ac.patch("/api/preferences/", json={"romanization_display": "rtgs"})
    rtgs = (await ac.get(f"/api/reading/texts/{text_id}")).json()["lines"][0]["romanization"]
    assert paiboon != rtgs and rtgs.startswith("khun")


HARD_DIALOGUE = {
    "title": "Hard",
    "lines": [
        {"speaker": "นิด", "word": "", "thai": t, "english": "x"}
        for t in ("กินข้าวกับฟูกเป่าลม", "ก่อสร้างอู่ซ่อมรถ", "ปั๊มน้ำมันพัง", "ที่นั่งผู้โดยสาร")
    ],
}


@pytest.mark.asyncio
async def test_too_hard_text_gets_one_simplify_pass(client, fake_llm):
    ac, factory = client
    topic_id, _ = await _seed(factory)
    fake_llm["gen"] = [HARD_DIALOGUE, DIALOGUE]  # first draft hard, rewrite simple
    r = await ac.post("/api/reading/texts", json={"kind": "dialogue", "topic_id": topic_id})
    text = (await ac.get(f"/api/reading/texts/{r.json()['id']}")).json()
    gen_calls = [c for c in fake_llm["calls"] if c[0] == LLMTask.READING_GENERATION]
    assert len(gen_calls) == 2 and "too hard" in gen_calls[1][1]
    assert text["title"] == "Hard" and text["lines"][0]["thai"] == "คุณกินข้าวหรือยังคะ"
    assert text["check"]["simplified"]


@pytest.mark.asyncio
async def test_easy_text_is_not_simplified(client, fake_llm):
    ac, factory = client
    topic_id, _ = await _seed(factory)
    await ac.post("/api/reading/texts", json={"kind": "dialogue", "topic_id": topic_id})
    assert [c[0] for c in fake_llm["calls"]] == [LLMTask.READING_GENERATION, LLMTask.READING_CHECK]


@pytest.mark.asyncio
async def test_usage_and_cost_are_recorded(client, fake_llm):
    ac, factory = client
    topic_id, _ = await _seed(factory)
    text_id = (await ac.post("/api/reading/texts", json={"kind": "dialogue", "topic_id": topic_id})).json()["id"]
    usage = (await ac.get(f"/api/reading/texts/{text_id}")).json()["usage"]
    # each call: 1000 in x $4/M + 500 out x $20/M = $0.014
    assert [c["step"] for c in usage["calls"]] == ["write", "check"]
    assert usage["total_cost"] == pytest.approx(0.028)
    est = {e["model"]: e["cost"] for e in usage["estimates"]}
    assert est["claude-sonnet-5-5"] == pytest.approx(0.014)
    assert est["claude-haiku-5-5"] == pytest.approx(0.0007)
    assert est["claude-fable-5-2"] == pytest.approx(0.056)
    [item] = (await ac.get("/api/reading/texts")).json()
    assert item["cost"] == pytest.approx(0.028)
