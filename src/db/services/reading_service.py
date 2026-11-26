"""Read & mine mode: read uploaded pages with known words highlighted.

Each page's stored OCR text is split into words; every Thai word gets a
status from the learner's own cards:

- ``known``    a card whose stability is at least ``mastery_stability_fragile_days``
               (the same 21-day line the Insights panel uses between "fragile"
               and "solid"), or a word marked "I know this" in the reader
- ``learning`` a card that has been studied but isn't solid yet
- ``new``      a card exists but hasn't been studied
- ``unknown``  no card at all

Cards can be multi-word phrases, so matching is greedy longest-match over up
to ``MAX_PHRASE_TOKENS`` consecutive tokens. Concatenating a line's segments
always gives back the original line, so the frontend can render it exactly.

Cards added from the reader go to the front of the new-card queue (their
schedule's ``fsrs_due`` is set to ``MINED_NEW_CARD_DUE``; new cards are
ordered by due date). They still count toward the daily new-card limit.
"""
from __future__ import annotations

import asyncio
import functools
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.db.models.card import Card
from src.db.models.card_schedule import CardSchedule
from src.db.models.deck import Deck
from src.db.models.reader_known_word import ReaderKnownWord
from src.db.models.upload import Upload
from src.db.models.upload_page import UploadPage

MAX_PHRASE_TOKENS = 4
READING_DECK_NAME = "Reading"
# Earlier than any real due date, so reader-added cards are introduced first.
MINED_NEW_CARD_DUE = datetime(2000, 1, 1, tzinfo=timezone.utc)

# Every Thai word contains a consonant; ๆ, ฯ and Thai digits alone are not words.
_THAI_LETTER = re.compile("[\u0E01-\u0E2E]")
_STATUS_RANK = {"known": 3, "learning": 2, "new": 1}

STATUSES = ("known", "learning", "new", "unknown")


def is_thai_word(token: str) -> bool:
    """True for tokens containing a Thai letter (not just ๆ, ฯ, digits, spaces)."""
    return bool(_THAI_LETTER.search(token))


@functools.lru_cache(maxsize=4096)
def tokenize_line(line: str) -> tuple[str, ...]:
    """Split a line into tokens that concatenate back to the line exactly."""
    from pythainlp.tokenize import word_tokenize
    from src.utils.thai_tokenize import merge_orphan_hor_nam

    if not is_thai_word(line):
        return (line,) if line else ()
    tokens = word_tokenize(line, engine="newmm", keep_whitespace=True)
    return tuple(merge_orphan_hor_nam([t for t in tokens if t]))


# ---------------------------------------------------------------------------
# Word index: what the learner knows
# ---------------------------------------------------------------------------

@dataclass
class WordIndex:
    status: dict[str, str] = field(default_factory=dict)  # thai -> known|learning|new
    card_id: dict[str, int] = field(default_factory=dict)
    max_tokens_by_first: dict[str, int] = field(default_factory=dict)

    def lookup(self, thai: str) -> Optional[str]:
        return self.status.get(thai)


def _schedule_status(state: str, stability: Optional[float], known_days: float) -> str:
    if state == "new":
        return "new"
    if state == "review" and stability is not None and stability >= known_days:
        return "known"
    return "learning"


async def build_word_index(db: AsyncSession, user_id: int) -> WordIndex:
    known_days = get_settings().mastery_stability_fragile_days
    index = WordIndex()

    rows = await db.execute(
        select(Card.id, Card.thai, CardSchedule.fsrs_state, CardSchedule.fsrs_stability)
        .join(CardSchedule, CardSchedule.card_id == Card.id)
    )
    for card_id, thai, state, stability in rows.all():
        thai = (thai or "").strip()
        if not thai:
            continue
        status = _schedule_status(state, stability, known_days)
        # A word can have several cards/directions: keep the best status.
        if _STATUS_RANK[status] > _STATUS_RANK.get(index.status.get(thai, ""), 0):
            index.status[thai] = status
            index.card_id[thai] = card_id
        else:
            index.card_id.setdefault(thai, card_id)

    marked = await db.scalars(select(ReaderKnownWord.thai).where(ReaderKnownWord.user_id == user_id))
    for thai in marked.all():
        index.status[thai] = "known"

    # For phrase matching: how many tokens the longest entry starting with a
    # given first token spans. Lets the matcher skip span lengths that can't hit.
    for thai in index.status:
        toks = [t for t in tokenize_line(thai) if t.strip()]
        n = min(len(toks), MAX_PHRASE_TOKENS)
        if toks and n > index.max_tokens_by_first.get(toks[0], 0):
            index.max_tokens_by_first[toks[0]] = n
    return index


# ---------------------------------------------------------------------------
# Segmentation + scoring
# ---------------------------------------------------------------------------

def segment_line(line: str, index: WordIndex) -> list[dict]:
    """[{text, status?, card_id?}] — Thai words get a status; everything else none."""
    tokens = tokenize_line(line)
    out: list[dict] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if not is_thai_word(tok):
            out.append({"text": tok})
            i += 1
            continue

        # Longest card/phrase match starting here (only Thai tokens, no spaces).
        best_len, best_text = 1, tok
        span_max = index.max_tokens_by_first.get(tok, 1)
        if span_max > 1:
            text = tok
            for j in range(i + 1, min(n, i + span_max)):
                if not is_thai_word(tokens[j]):
                    break
                text += tokens[j]
                if index.lookup(text):
                    best_len, best_text = j - i + 1, text

        status = index.lookup(best_text)
        parts = None if status else split_into_known(best_text, index)
        for part in parts or [best_text]:
            seg = {"text": part, "status": index.lookup(part) or "unknown"}
            if part in index.card_id:
                seg["card_id"] = index.card_id[part]
            out.append(seg)
        i += best_len
    return out


def split_into_known(token: str, index: WordIndex, max_part: int = 20) -> Optional[list[str]]:
    """Split a token the tokenizer kept whole (e.g. กินข้าว) into words that
    all have a status, preferring the fewest parts. None if no full split."""
    n = len(token)
    if n < 2:
        return None
    best: list[Optional[list[str]]] = [None] * (n + 1)
    best[0] = []
    for end in range(1, n + 1):
        for start in range(max(0, end - max_part), end):
            prev = best[start]
            piece = token[start:end]
            if prev is not None and index.lookup(piece) and is_thai_word(piece):
                cand = prev + [piece]
                if best[end] is None or len(cand) < len(best[end]):
                    best[end] = cand
    split = best[n]
    return split if split and len(split) > 1 else None


def segment_text(text: str, index: WordIndex) -> list[list[dict]]:
    return [segment_line(line, index) for line in (text or "").split("\n")]


def score(lines: list[list[dict]]) -> dict:
    counts = {s: 0 for s in STATUSES}
    unknown_words: set[str] = set()
    for line in lines:
        for seg in line:
            status = seg.get("status")
            if status:
                counts[status] += 1
                if status == "unknown":
                    unknown_words.add(seg["text"])
    total = sum(counts.values())
    return {
        "thai_words": total,
        "counts": counts,
        "known_pct": round(100 * counts["known"] / total) if total else None,
        "unknown_unique": len(unknown_words),
    }


# ---------------------------------------------------------------------------
# Uploads / pages
# ---------------------------------------------------------------------------

def upload_title(upload: Upload, parent: Optional[Upload] = None) -> str:
    return (
        upload.chapter_label
        or upload.section_label
        or upload.source_title
        or (parent.source_title if parent else None)
        or upload.filename
    )


async def list_readable(db: AsyncSession, user_id: int) -> list[dict]:
    """Uploads with stored page text, each with a whole-upload known score."""
    index = await build_word_index(db, user_id)

    pages = (await db.execute(
        select(UploadPage.upload_id, UploadPage.page_index, UploadPage.text)
        .where(UploadPage.text.isnot(None))
        .order_by(UploadPage.upload_id, UploadPage.page_index)
    )).all()
    # Same page set the reader steps through (every page with text); an
    # upload is listed only if at least one of its pages has Thai on it.
    by_upload: dict[int, list[str]] = {}
    for upload_id, _, text in pages:
        by_upload.setdefault(upload_id, []).append(text or "")
    by_upload = {uid: texts for uid, texts in by_upload.items() if any(is_thai_word(t) for t in texts)}
    if not by_upload:
        return []

    uploads = {
        u.id: u for u in (await db.scalars(select(Upload).where(Upload.id.in_(by_upload)))).all()
    }
    parent_ids = {u.parent_upload_id for u in uploads.values() if u.parent_upload_id}
    parents = {
        u.id: u for u in (await db.scalars(select(Upload).where(Upload.id.in_(parent_ids)))).all()
    } if parent_ids else {}

    def _score_upload(texts: list[str]) -> dict:
        lines: list[list[dict]] = []
        for t in texts:
            lines.extend(segment_text(t, index))
        return score(lines)

    result = []
    for upload_id, texts in by_upload.items():
        upload = uploads.get(upload_id)
        if upload is None:
            continue
        parent = parents.get(upload.parent_upload_id) if upload.parent_upload_id else None
        stats = await asyncio.to_thread(_score_upload, texts)
        result.append({
            "upload_id": upload_id,
            "title": upload_title(upload, parent),
            "book_id": parent.id if parent else None,
            "book_title": (parent.source_title or parent.filename) if parent else None,
            "filename": upload.filename,
            "pages": len(texts),
            **stats,
        })
    result.sort(key=lambda r: (r["book_title"] or r["title"], r["upload_id"]))
    return result


async def get_page(db: AsyncSession, user_id: int, upload_id: int, page_index: int) -> Optional[dict]:
    upload = await db.get(Upload, upload_id)
    if upload is None:
        return None
    page_indexes = (await db.scalars(
        select(UploadPage.page_index)
        .where(UploadPage.upload_id == upload_id, UploadPage.text.isnot(None))
        .order_by(UploadPage.page_index)
    )).all()
    if page_index not in page_indexes:
        return None
    page = await db.scalar(
        select(UploadPage).where(UploadPage.upload_id == upload_id, UploadPage.page_index == page_index)
    )
    parent = await db.get(Upload, upload.parent_upload_id) if upload.parent_upload_id else None
    index = await build_word_index(db, user_id)
    lines = await asyncio.to_thread(segment_text, page.text, index)

    pos = page_indexes.index(page_index)
    return {
        "upload_id": upload_id,
        "title": upload_title(upload, parent),
        "book_title": (parent.source_title or parent.filename) if parent else None,
        "page_index": page_index,
        "page_number": pos + 1,
        "page_count": len(page_indexes),
        "prev_page": page_indexes[pos - 1] if pos > 0 else None,
        "next_page": page_indexes[pos + 1] if pos + 1 < len(page_indexes) else None,
        "lines": lines,
        "stats": score(lines),
    }


# ---------------------------------------------------------------------------
# Word actions
# ---------------------------------------------------------------------------

async def lookup_word(db: AsyncSession, user_id: int, thai: str) -> dict:
    from src.db.services.preferences_service import get_preferences
    from src.utils.compound import gloss_candidates
    from src.utils.romanization import generate_all, resolve_effective

    prefs = await get_preferences(db)
    schemes = await asyncio.to_thread(generate_all, thai)
    romanization = resolve_effective(
        {
            "romanization_source": None,
            "romanization_paiboon": schemes.get("paiboon") or None,
            "romanization_rtgs": schemes.get("rtgs") or None,
            "romanization_ipa": schemes.get("ipa") or None,
            "romanization_manual": None,
        },
        prefs,
    )
    glosses = await gloss_candidates(db, thai)

    card = await db.scalar(select(Card).where(Card.thai == thai).order_by(Card.id).limit(1))
    marked = await db.scalar(
        select(func.count(ReaderKnownWord.id))
        .where(ReaderKnownWord.user_id == user_id, ReaderKnownWord.thai == thai)
    )
    return {
        "thai": thai,
        "romanization": romanization,
        "glosses": [{"gloss": g["gloss"], "source": g["source"]} for g in glosses[:6]],
        "card": {"id": card.id, "english": card.english, "deck_id": card.deck_id} if card else None,
        "marked_known": bool(marked),
    }


async def _deck_for_upload(db: AsyncSession, upload: Optional[Upload]) -> int:
    if upload is not None:
        if upload.deck_id:
            return upload.deck_id
        if upload.parent_upload_id:
            parent = await db.get(Upload, upload.parent_upload_id)
            if parent and parent.deck_id:
                return parent.deck_id
    deck = await db.scalar(
        select(Deck).where(Deck.name == READING_DECK_NAME, Deck.deleted_at.is_(None))
    )
    if deck is None:
        deck = Deck(name=READING_DECK_NAME, description="Words added while reading")
        db.add(deck)
        await db.flush()
    return deck.id


async def add_card(
    db: AsyncSession,
    thai: str,
    english: str,
    upload_id: Optional[int] = None,
    example_thai: Optional[str] = None,
) -> tuple[Card, bool]:
    """Create a card for a word met while reading. Returns (card, created)."""
    from src.db.services import card_service
    from src.db.services.preferences_service import get_preferences
    from src.utils.romanization import generate_all, resolve_effective

    upload = await db.get(Upload, upload_id) if upload_id else None
    deck_id = await _deck_for_upload(db, upload)

    existing = await db.scalar(select(Card).where(Card.deck_id == deck_id, Card.thai == thai))
    if existing is not None:
        return existing, False

    prefs = await get_preferences(db)
    schemes = await asyncio.to_thread(generate_all, thai)
    values = {
        "romanization_source": None,
        "romanization_paiboon": schemes.get("paiboon") or None,
        "romanization_rtgs": schemes.get("rtgs") or None,
        "romanization_ipa": schemes.get("ipa") or None,
        "romanization_manual": None,
    }
    card = await card_service.create_card(
        db,
        deck_id=deck_id,
        thai=thai,
        english=english,
        romanization=resolve_effective(values, prefs),
        romanization_paiboon=values["romanization_paiboon"],
        romanization_rtgs=values["romanization_rtgs"],
        romanization_ipa=values["romanization_ipa"],
        example_thai=example_thai,
        source_upload_id=upload_id,
    )
    schedule = await db.scalar(select(CardSchedule).where(CardSchedule.card_id == card.id))
    if schedule is not None:
        schedule.fsrs_due = MINED_NEW_CARD_DUE
    # The word is no longer "known without a card".
    await db.execute(delete(ReaderKnownWord).where(ReaderKnownWord.thai == thai))
    await db.flush()
    return card, True


async def mark_known(db: AsyncSession, user_id: int, thai: str, known: bool) -> None:
    existing = await db.scalar(
        select(ReaderKnownWord).where(ReaderKnownWord.user_id == user_id, ReaderKnownWord.thai == thai)
    )
    if known and existing is None:
        db.add(ReaderKnownWord(user_id=user_id, thai=thai))
    elif not known and existing is not None:
        await db.delete(existing)
    await db.flush()
