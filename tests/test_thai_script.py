"""
Tests for converting romanized/English text in a card's Thai field into
Thai script: src/db/services/thai_script_service.py and the card-generation
guard in src/tasks/upload_tasks.py. Claude is replaced by a fake provider.

    pytest tests/test_thai_script.py -v
"""
import json

import pytest

from src.db.models import Card
from src.db.services import thai_script_service as tss
from src.llm.base import LLMResponse
from src.practice.registry import LISTEN_TH_EN
from src.tasks import upload_tasks


class FakeProvider:
    def __init__(self, rows=None, fail=False):
        self.rows, self.fail, self.calls = rows or [], fail, []

    async def complete(self, messages, **kwargs):
        self.calls.append((json.loads(messages[-1].content), kwargs))
        if self.fail:
            raise RuntimeError("model down")
        return LLMResponse(text=json.dumps({"items": self.rows}, ensure_ascii=False),
                           input_tokens=10, output_tokens=10, model="claude-sonnet-5-5")


@pytest.fixture
def fake(monkeypatch):
    holder = {}

    def install(**kw):
        holder["p"] = FakeProvider(**kw)
        monkeypatch.setattr(tss, "get_provider", lambda task: holder["p"])
        return holder["p"]

    return install


def _row(i, thai, source="romanization", confidence="high", note=""):
    return {"index": i, "thai": thai, "source": source, "confidence": confidence, "note": note}


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------

def test_detection():
    assert tss.has_thai_script("คุณปิดพัดลมได้ไหม")
    assert not tss.has_thai_script("khun pìt phátˑlom dâay mǎy")
    assert not tss.has_thai_script("")
    assert tss.looks_romanized("khun pìt phátˑlom dâay mǎy")
    assert tss.looks_romanized("anˑníi phɛɛŋ kwàa")
    assert not tss.looks_romanized("What time is it?")
    assert not tss.looks_romanized("Jazz")
    assert not tss.looks_romanized("กิน")


def test_agreement_is_high_for_a_match_and_low_for_a_mismatch():
    assert tss.agreement("khun pìt phátˑlom dâay mǎy", "คุณปิดพัดลมได้ไหม") >= 0.7
    assert tss.agreement("khun pìt phátˑlom dâay mǎy", "แมว") < 0.5


# ---------------------------------------------------------------------------
# to_thai_script
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_to_thai_script_validates_model_output(fake):
    provider = fake(rows=[
        _row(0, "คุณปิดพัดลมได้ไหม"),
        _row(1, "khun pìt"),                 # still romanized -> rejected
        _row(2, "แจ๊ส", source="english"),
        _row(3, "กี่โมง abc"),               # Latin mixed in -> rejected
        _row(9, "ผิด"),                      # out-of-range index -> ignored
    ])
    out = await tss.to_thai_script([
        {"text": "khun pìt phátˑlom dâay mǎy", "english": "Can you turn off the fan?", "hint": "คุณปิดพัดลมได้ไหม"},
        {"text": "x", "english": "y"},
        {"text": "Jazz", "english": "jazz"},
        {"text": "z", "english": "w"},
    ])
    assert out[0].thai == "คุณปิดพัดลมได้ไหม" and out[0].source == "romanization"
    assert out[1] is None and out[3] is None
    assert out[2].thai == "แจ๊ส" and out[2].source == "english"
    sent, kwargs = provider.calls[0]
    assert sent[0]["hint"] == "คุณปิดพัดลมได้ไหม"
    assert "json_schema" in kwargs


# ---------------------------------------------------------------------------
# card-generation guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_guard_converts_flags_and_keeps_book_romanization(fake):
    fake(rows=[_row(0, "คุณปิดพัดลมได้ไหม", note=""), _row(1, "แจ๊ส", source="english", confidence="low", note="loanword")])
    cards = [
        {"thai": "กิน", "english": "eat", "romanization": None},
        {"thai": "khun pìt phátˑlom dâay mǎy", "english": "Can you turn off the fan?", "romanization": None},
        {"thai": "Jazz", "english": "jazz", "romanization": None},
    ]
    flags = await upload_tasks._ensure_thai_script(1, cards)
    assert [c["thai"] for c in cards] == ["กิน", "คุณปิดพัดลมได้ไหม", "แจ๊ส"]
    assert cards[1]["romanization"] == "khun pìt phátˑlom dâay mǎy"
    assert cards[2]["romanization"] is None  # English isn't romanization
    assert [f["thai"] for f in flags] == ["คุณปิดพัดลมได้ไหม", "แจ๊ส"]
    assert all(f["reason"] == "converted_to_thai_script" for f in flags)
    assert flags[1]["note"] == "loanword"


@pytest.mark.asyncio
async def test_guard_drops_cards_it_cannot_convert(fake):
    fake(fail=True)
    cards = [
        {"thai": "กิน", "english": "eat"},
        {"thai": "khun pìt", "english": "you close"},
    ]
    flags = await upload_tasks._ensure_thai_script(1, cards)
    assert flags == []
    assert [c["thai"] for c in cards] == ["กิน"]


@pytest.mark.asyncio
async def test_guard_makes_no_call_when_all_cards_have_thai(fake):
    provider = fake(rows=[])
    cards = [{"thai": "กิน", "english": "eat"}]
    assert await upload_tasks._ensure_thai_script(1, cards) == []
    assert provider.calls == []


def test_listening_skips_cards_without_thai_script():
    assert not LISTEN_TH_EN.is_eligible(Card(thai="khun pìt phátˑlom", english="close the fan", card_type="phrase"))
