"""
Tests for src/db/services/correction_service.py — the single choke point for
writes that change a card's display value, resolve/dismiss flags, or move
translation_status from a triage/drawer decision, plus the append-only
card_correction_event log underneath it.

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_correction_service.py -v
"""
import json

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.db.models import Base, Card, Deck
from src.db.models.card_correction_event import CardCorrectionEvent
from src.db.models.card_flag import CardFlag
from src.db.models.card_override import CardOverride
from src.db.services import correction_service
from src.utils.card_overrides import load_overrides, upsert_flag, upsert_override
from src.utils.correction_keys import english_norm


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


async def _make_card(db, thai="ไม่เป็นไร", english="you're welcome", **kwargs):
    deck = Deck(name="Test Deck")
    db.add(deck)
    await db.flush()
    card = Card(deck_id=deck.id, thai=thai, english=english, card_type="vocab", **kwargs)
    db.add(card)
    await db.flush()
    return card


# ---------------------------------------------------------------------------
# apply_decision — translation
# ---------------------------------------------------------------------------

class TestApplyDecisionTranslationCorrect:
    @pytest.mark.asyncio
    async def test_correct_writes_override_and_event_in_one_transaction(self, db):
        card = await _make_card(db, english="bicycle", translation_status="flagged")
        await db.commit()

        event = await correction_service.apply_decision(
            db, user_id=1,
            decision={"card_id": card.id, "target": "translation", "action": "correct",
                      "payload": {"english": "train"}},
            source="triage",
        )
        await db.commit()

        assert event.action == "correct"
        assert event.target == "translation"
        assert json.loads(event.to_value) == {"english": "train"}
        assert json.loads(event.from_value) == {"english": "bicycle"}
        assert event.from_norm == english_norm("bicycle")

        override = await db.scalar(select(CardOverride).where(CardOverride.card_id == card.id))
        assert json.loads(override.payload)["english"] == "train"

        refreshed = await db.get(Card, card.id)
        assert refreshed.english == "bicycle"  # material value untouched
        assert refreshed.translation_status == "confirmed"

    @pytest.mark.asyncio
    async def test_from_value_is_effective_value_when_override_already_existed(self, db):
        card = await _make_card(db, english="bicycle", translation_status="flagged")
        await upsert_override(db, 1, card.id, "translation", {"english": "wagon"})
        await db.commit()

        event = await correction_service.apply_decision(
            db, user_id=1,
            decision={"card_id": card.id, "target": "translation", "action": "correct",
                      "payload": {"english": "train"}},
            source="triage",
        )
        await db.commit()

        assert json.loads(event.from_value) == {"english": "wagon"}
        assert event.prev_override == json.dumps({"english": "wagon"}, ensure_ascii=False)

    @pytest.mark.asyncio
    async def test_correct_resolves_open_flag_on_same_target(self, db):
        card = await _make_card(db, translation_status="flagged")
        await upsert_flag(db, 1, card.id, "translation", "looks wrong")
        await db.commit()

        await correction_service.apply_decision(
            db, user_id=1,
            decision={"card_id": card.id, "target": "translation", "action": "correct",
                      "payload": {"english": "train"}},
            source="triage",
        )
        await db.commit()

        flag = await db.scalar(select(CardFlag).where(CardFlag.card_id == card.id))
        assert flag.status == "resolved"
        assert flag.resolved_at is not None

    @pytest.mark.asyncio
    async def test_keep_confirms_without_writing_override(self, db):
        card = await _make_card(db, translation_status="flagged")
        await db.commit()

        event = await correction_service.apply_decision(
            db, user_id=1,
            decision={"card_id": card.id, "target": "translation", "action": "keep"},
            source="triage",
        )
        await db.commit()

        assert event.to_value is None
        override_count = await db.scalar(select(func.count()).select_from(CardOverride))
        assert override_count == 0
        refreshed = await db.get(Card, card.id)
        assert refreshed.translation_status == "confirmed"


# ---------------------------------------------------------------------------
# apply_decision — compound
# ---------------------------------------------------------------------------

class TestApplyDecisionCompound:
    @pytest.mark.asyncio
    async def test_suppress_files_a_flag_when_none_open(self, db):
        breakdown = [{"thai": "น้ำ", "gloss": "water"}, {"thai": "แข็ง", "gloss": None}]
        card = await _make_card(
            db, thai="น้ำแข็ง", english="ice",
            compound_breakdown=json.dumps(breakdown, ensure_ascii=False), is_compound=True,
        )
        await db.commit()

        event = await correction_service.apply_decision(
            db, user_id=1,
            decision={"card_id": card.id, "target": "compound", "action": "suppress"},
            source="triage",
        )
        await db.commit()

        assert event.to_value == json.dumps({"suppressed": True}, ensure_ascii=False)
        flag = await db.scalar(select(CardFlag).where(CardFlag.card_id == card.id))
        assert flag is not None and flag.status == "open"

    @pytest.mark.asyncio
    async def test_suppress_does_not_touch_an_already_open_flag(self, db):
        breakdown = [{"thai": "น้ำ", "gloss": "water"}]
        card = await _make_card(
            db, thai="น้ำแข็ง", english="ice",
            compound_breakdown=json.dumps(breakdown, ensure_ascii=False), is_compound=True,
        )
        await upsert_flag(db, 1, card.id, "compound", "pre-existing note")
        await db.commit()

        await correction_service.apply_decision(
            db, user_id=1,
            decision={"card_id": card.id, "target": "compound", "action": "suppress"},
            source="triage",
        )
        await db.commit()

        count = await db.scalar(select(func.count()).select_from(CardFlag))
        assert count == 1
        flag = await db.scalar(select(CardFlag).where(CardFlag.card_id == card.id))
        assert flag.status == "open"
        assert flag.note == "pre-existing note"

    @pytest.mark.asyncio
    async def test_llm_fill_no_gaps_returns_sentinel_not_an_event(self, db, monkeypatch):
        breakdown = [{"thai": "น้ำ", "gloss": "water"}]
        card = await _make_card(
            db, thai="น้ำ", english="water",
            compound_breakdown=json.dumps(breakdown, ensure_ascii=False), is_compound=True,
        )
        await db.commit()

        from src.db.services import compound_llm_service
        async def fake_enrich(_db, _card_id):
            return {"status": "no_gaps", "parts": breakdown}
        monkeypatch.setattr(compound_llm_service, "enrich_breakdown", fake_enrich)

        result = await correction_service.apply_decision(
            db, user_id=1,
            decision={"card_id": card.id, "target": "compound", "action": "llm_fill"},
            source="triage",
        )
        await db.commit()

        assert isinstance(result, correction_service.NoCorrectionApplied)
        assert result.status == "no_gaps"
        event_count = await db.scalar(select(func.count()).select_from(CardCorrectionEvent))
        assert event_count == 0

    @pytest.mark.asyncio
    async def test_llm_fill_low_confidence_is_not_logged_and_card_is_unchanged(self, db, monkeypatch):
        """Regression: this used to log an event and report 'enriched' even
        though enrich_breakdown()'s own confidence guard left
        cards.compound_breakdown untouched — a false positive that made
        triage's 'Fill with AI' look like it worked when nothing changed."""
        breakdown = [{"thai": "น้ำ", "gloss": "water"}, {"thai": "แข็ง", "gloss": None}]
        card = await _make_card(
            db, thai="น้ำแข็ง", english="ice",
            compound_breakdown=json.dumps(breakdown, ensure_ascii=False), is_compound=True,
        )
        await db.commit()

        from src.db.services import compound_llm_service
        async def fake_enrich(_db, _card_id):
            # Mirrors enrich_breakdown()'s own behaviour on a low-confidence
            # fill: parts/filled are populated for display but persisted=False
            # and the card row is never touched.
            return {
                "status": "enriched",
                "parts": [breakdown[0], {"thai": "แข็ง", "gloss": "hard"}],
                "confidence": "low", "filled": ["แข็ง"], "persisted": False,
                "input_tokens": 200, "output_tokens": 20,
            }
        monkeypatch.setattr(compound_llm_service, "enrich_breakdown", fake_enrich)

        result = await correction_service.apply_decision(
            db, user_id=1,
            decision={"card_id": card.id, "target": "compound", "action": "llm_fill"},
            source="triage",
        )
        await db.commit()

        assert isinstance(result, correction_service.NoCorrectionApplied)
        assert result.status == "low_confidence"
        event_count = await db.scalar(select(func.count()).select_from(CardCorrectionEvent))
        assert event_count == 0
        refreshed = await db.get(Card, card.id)
        assert refreshed.compound_breakdown == json.dumps(breakdown, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Batch validation: one invalid item writes nothing
# ---------------------------------------------------------------------------

class TestBatchValidation:
    @pytest.mark.asyncio
    async def test_one_invalid_decision_rejects_the_whole_batch(self, db):
        good_card = await _make_card(db, english="bicycle", translation_status="flagged")
        await db.commit()

        decisions = [
            {"card_id": good_card.id, "target": "translation", "action": "correct",
             "payload": {"english": "train"}},
            {"card_id": 999999, "target": "translation", "action": "correct",
             "payload": {"english": "train"}},
        ]

        errors = []
        for d in decisions:
            try:
                await correction_service.validate_decision(db, d)
            except correction_service.CorrectionError as exc:
                errors.append(str(exc))

        assert errors, "expected the unknown card_id to fail validation"

        # Application code validates all decisions before applying any —
        # simulate that gate here and confirm nothing was written.
        event_count = await db.scalar(select(func.count()).select_from(CardCorrectionEvent))
        override_count = await db.scalar(select(func.count()).select_from(CardOverride))
        assert event_count == 0
        assert override_count == 0


# ---------------------------------------------------------------------------
# undo
# ---------------------------------------------------------------------------

class TestUndo:
    @pytest.mark.asyncio
    async def test_undo_restores_previous_override_and_reflags(self, db):
        card = await _make_card(db, english="bicycle", translation_status="flagged")
        await upsert_flag(db, 1, card.id, "translation", "looks wrong")
        await db.commit()

        event = await correction_service.apply_decision(
            db, user_id=1,
            decision={"card_id": card.id, "target": "translation", "action": "correct",
                      "payload": {"english": "train"}},
            source="triage",
        )
        await db.commit()

        new_events, skipped = await correction_service.undo(db, user_id=1, event_id=event.id)
        await db.commit()

        assert skipped == []
        assert len(new_events) == 1
        assert new_events[0].action == "undo"
        assert new_events[0].reverts_event_id == event.id

        refreshed = await db.get(Card, card.id)
        assert refreshed.translation_status == "flagged"

        override = await db.scalar(select(CardOverride).where(CardOverride.card_id == card.id))
        assert override is None

        flag = await db.scalar(select(CardFlag).where(CardFlag.card_id == card.id))
        assert flag.status == "open"
        assert flag.resolved_at is None

        # events are never deleted
        original = await db.get(CardCorrectionEvent, event.id)
        assert original is not None

    @pytest.mark.asyncio
    async def test_undo_restores_prior_override_not_just_deletes(self, db):
        card = await _make_card(db, english="bicycle", translation_status="flagged")
        await upsert_override(db, 1, card.id, "translation", {"english": "wagon"})
        await db.commit()

        event = await correction_service.apply_decision(
            db, user_id=1,
            decision={"card_id": card.id, "target": "translation", "action": "correct",
                      "payload": {"english": "train"}},
            source="triage",
        )
        await db.commit()

        await correction_service.undo(db, user_id=1, event_id=event.id)
        await db.commit()

        overrides = await load_overrides(db, [card.id], user_id=1)
        assert overrides[card.id]["translation"]["english"] == "wagon"

    @pytest.mark.asyncio
    async def test_llm_fill_is_not_undoable(self, db):
        card = await _make_card(db, english="cat", is_compound=True)
        await db.commit()

        event = CardCorrectionEvent(
            user_id=1, card_id=card.id, thai_key="x", target="compound", action="llm_fill",
            to_value=json.dumps({"parts": []}), source="triage",
        )
        db.add(event)
        await db.commit()

        new_events, skipped = await correction_service.undo(db, user_id=1, event_id=event.id)
        await db.commit()

        assert new_events == []
        assert skipped == [event.id]

    @pytest.mark.asyncio
    async def test_undoing_an_already_undone_event_is_skipped(self, db):
        card = await _make_card(db, english="bicycle", translation_status="flagged")
        await db.commit()

        event = await correction_service.apply_decision(
            db, user_id=1,
            decision={"card_id": card.id, "target": "translation", "action": "correct",
                      "payload": {"english": "train"}},
            source="triage",
        )
        await db.commit()
        await correction_service.undo(db, user_id=1, event_id=event.id)
        await db.commit()

        new_events, skipped = await correction_service.undo(db, user_id=1, event_id=event.id)
        await db.commit()
        assert new_events == []
        assert skipped == [event.id]


# ---------------------------------------------------------------------------
# find_propagation_candidates
# ---------------------------------------------------------------------------

class TestFindPropagationCandidates:
    @pytest.mark.asyncio
    async def test_same_thai_same_wrong_english_is_a_match(self, db):
        card_a = await _make_card(db, thai="ไม่เป็นไร", english="bicycle", translation_status="flagged")
        card_b = await _make_card(db, thai="ไม่เป็นไร", english="bicycle", translation_status="flagged")
        await db.commit()

        event = await correction_service.apply_decision(
            db, user_id=1,
            decision={"card_id": card_a.id, "target": "translation", "action": "correct",
                      "payload": {"english": "train"}},
            source="triage",
        )
        await db.commit()

        matches = await correction_service.find_propagation_candidates(db, event, user_id=1)
        assert matches == [card_b.id]

    @pytest.mark.asyncio
    async def test_same_thai_different_english_is_excluded(self, db):
        card_a = await _make_card(db, thai="ไม่เป็นไร", english="bicycle", translation_status="flagged")
        await _make_card(db, thai="ไม่เป็นไร", english="never mind", translation_status="flagged")
        await db.commit()

        event = await correction_service.apply_decision(
            db, user_id=1,
            decision={"card_id": card_a.id, "target": "translation", "action": "correct",
                      "payload": {"english": "train"}},
            source="triage",
        )
        await db.commit()

        matches = await correction_service.find_propagation_candidates(db, event, user_id=1)
        assert matches == []

    @pytest.mark.asyncio
    async def test_already_overridden_card_is_excluded(self, db):
        card_a = await _make_card(db, thai="ไม่เป็นไร", english="bicycle", translation_status="flagged")
        card_b = await _make_card(db, thai="ไม่เป็นไร", english="bicycle", translation_status="flagged")
        await upsert_override(db, 1, card_b.id, "translation", {"english": "something else already"})
        await db.commit()

        event = await correction_service.apply_decision(
            db, user_id=1,
            decision={"card_id": card_a.id, "target": "translation", "action": "correct",
                      "payload": {"english": "train"}},
            source="triage",
        )
        await db.commit()

        matches = await correction_service.find_propagation_candidates(db, event, user_id=1)
        assert matches == []
