"""Generated reading practice: dialogues and example sentences written by
Claude around the vocabulary of a topic or chapter.

Pipeline for one text:
1. Offer up to ``CANDIDATES`` words from the scope's cards: words being
   learnt first, then known ones, and at most ``MAX_NEW_CANDIDATES`` never
   studied. The writer uses only the 3-4 that fit one natural scene, so the
   story isn't bent around unrelated words.
2. Tell the writer the learner's real vocabulary size and give it the words
   they know, so it writes at their level.
3. Generate (READING_GENERATION). Then measure difficulty locally: words that
   are neither known, nor practice words, nor among the most common Thai
   words. If there are more than ``MAX_HARD_WORDS``, ask for one simpler
   rewrite naming those words, and keep whichever version is easier.
4. Check (READING_CHECK): the checker first judges the whole text (coherent?
   natural? beginner-level?) and rewrites it if not, otherwise fixes single
   lines. If the check call fails, the text is still saved, marked unchecked.
5. Store romanization per line; render through reading_service so words get
   the same known / learning / new / unknown colouring as uploaded pages.
"""
from __future__ import annotations

import asyncio
import functools
import json
import random
from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.card import Card
from src.db.models.generated_text import GeneratedText
from src.db.models.topic import CardTopic, Topic
from src.db.models.upload import Upload
from src.db.services import reading_service
from src.llm.base import LLMMessage
from src.llm import pricing
from src.llm.prompts import reading_generation as prompts
from src.llm.registry import LLMTask, get_provider
from src.utils.text_integrity import find_invalid_chars, normalise_text

KINDS = ("dialogue", "sentences")
SCOPES = ("topic", "upload")
CANDIDATES = 12
MAX_NEW_CANDIDATES = 3  # never-studied words offered; keeps texts within reach
MIN_TARGETS = 3
MAX_KNOWN_WORDS = 400
MAX_TARGET_CHARS = 20  # skip whole-sentence cards as targets
MIN_LINES = 3
COMMON_WORDS = 800  # top of the Thai National Corpus list counts as "common"
MAX_HARD_WORDS = 4  # distinct uncommon words outside the learner's vocabulary


class GenerationError(Exception):
    """Generation couldn't produce a usable text; message is user-facing."""


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

async def scope_label(db: AsyncSession, scope: str, scope_id: int) -> Optional[str]:
    if scope == "topic":
        topic = await db.get(Topic, scope_id)
        return topic.name if topic else None
    upload = await db.get(Upload, scope_id)
    if upload is None:
        return None
    parent = await db.get(Upload, upload.parent_upload_id) if upload.parent_upload_id else None
    return reading_service.upload_title(upload, parent)


async def _scope_cards(db: AsyncSession, scope: str, scope_id: int) -> list[Card]:
    stmt = select(Card)
    if scope == "topic":
        stmt = stmt.join(CardTopic, CardTopic.card_id == Card.id).where(CardTopic.topic_id == scope_id)
    else:
        stmt = stmt.where(Card.source_upload_id == scope_id)
    return list((await db.scalars(stmt)).all())


def pick_candidates(
    cards: list[Card],
    index: reading_service.WordIndex,
    rng: random.Random,
    n: int = CANDIDATES,
    max_new: int = MAX_NEW_CANDIDATES,
) -> list[dict]:
    """Learning words first, then known (reinforcement), then a few unstudied."""
    buckets: dict[str, list[dict]] = {"learning": [], "known": [], "new": []}
    seen: set[str] = set()
    for card in cards:
        thai = (card.thai or "").strip()
        if not thai or thai in seen or len(thai) > MAX_TARGET_CHARS or card.card_type == "grammar":
            continue
        seen.add(thai)
        status = index.lookup(thai) or "new"
        buckets.get(status, buckets["new"]).append({"thai": thai, "english": card.english, "status": status})
    picked: list[dict] = []
    for name, cap in (("learning", n), ("known", n), ("new", max_new)):
        group = buckets[name]
        rng.shuffle(group)
        picked.extend(group[: min(cap, n - len(picked))])
    return picked


def known_words(index: reading_service.WordIndex, exclude: set[str], rng: random.Random) -> list[str]:
    words = [
        w for w, s in index.status.items()
        if s in ("known", "learning") and w not in exclude and len(w) <= MAX_TARGET_CHARS
    ]
    rng.shuffle(words)
    return sorted(words[:MAX_KNOWN_WORDS], key=len)


@functools.lru_cache(maxsize=1)
def common_words() -> frozenset[str]:
    """Most frequent Thai words (Thai National Corpus, bundled with PyThaiNLP)."""
    try:
        from pythainlp.corpus import ttc
        freqs = sorted(ttc.word_freqs(), key=lambda x: -x[1])
        return frozenset(w for w, _ in freqs[:COMMON_WORDS])
    except Exception as exc:  # pragma: no cover - corpus is bundled
        logger.warning(f"Thai frequency list unavailable: {exc!r}")
        return frozenset()


def hard_words(lines: list[dict], index: reading_service.WordIndex, practice: set[str]) -> list[str]:
    """Distinct words a beginner would struggle with: not known or learning,
    not a practice word, not among the most common Thai words."""
    common = common_words()
    hard = []
    for line in lines:
        for seg in reading_service.segment_line(line["thai"], index):
            word = seg["text"]
            if seg.get("status") not in ("unknown", "new"):
                continue
            if word in practice or word in common or word in hard:
                continue
            hard.append(word)
    return hard


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def _clean_thai(text: str) -> Optional[str]:
    thai, _ = normalise_text((text or "").strip())
    if not thai or not reading_service.is_thai_word(thai) or find_invalid_chars(thai):
        return None
    return thai


def _clean_lines(raw_lines: list[dict]) -> list[dict]:
    lines = []
    for raw in raw_lines or []:
        thai = _clean_thai(raw.get("thai", ""))
        english = (raw.get("english") or "").strip()
        if thai is None or not english:
            continue
        lines.append({
            "speaker": (raw.get("speaker") or "").strip(),
            "word": (raw.get("word") or "").strip(),
            "thai": thai,
            "english": english,
        })
    return lines


async def _ask_json(
    task: LLMTask, system: str, user: str, schema: dict, calls: list[dict], step: str
) -> tuple[dict, str]:
    """Call the model for JSON; appends the call's token usage to ``calls``."""
    provider = get_provider(task)
    response = await provider.complete(
        [LLMMessage(role="system", content=system), LLMMessage(role="user", content=user)],
        json_schema=schema,
    )
    calls.append(pricing.call_record(step, response))
    return json.loads(response.text), response.model


def apply_check(lines: list[dict], result: dict) -> tuple[list[dict], dict]:
    """Apply the checker's verdict; returns (lines, check summary).

    A whole-text rewrite (overall.natural false) replaces the lines; otherwise
    single-line fixes are applied.
    """
    overall = result.get("overall") or {}
    if overall.get("natural") is False:
        rewrite = _clean_lines(result.get("rewrite") or [])
        if len(rewrite) >= MIN_LINES:
            for line in rewrite:
                line["fixed"] = True
            return rewrite, {
                "checked": True,
                "rewritten": True,
                "problem": (overall.get("problem") or "").strip(),
                "fixed": len(rewrite),
                "notes": [],
            }

    fixed = 0
    notes = []
    out = [dict(l) for l in lines]
    for v in result.get("lines") or []:
        i = v.get("index")
        if not isinstance(i, int) or not 0 <= i < len(out) or v.get("verdict") != "fixed":
            continue
        thai = _clean_thai(v.get("thai", ""))
        english = (v.get("english") or "").strip()
        changed = False
        if thai and thai != out[i]["thai"]:
            out[i]["thai"] = thai
            changed = True
        if english and english != out[i]["english"]:
            out[i]["english"] = english
            changed = True
        if changed:
            fixed += 1
            out[i]["fixed"] = True
            if v.get("note"):
                notes.append({"index": i, "note": v["note"].strip()})
    return out, {"checked": True, "rewritten": False, "problem": "", "fixed": fixed, "notes": notes}


def _romanize_lines(lines: list[dict]) -> bool:
    """Add {paiboon, rtgs, ipa} romanization to lines missing it (slow:
    ~0.5 s a line, so it's stored with the text, not computed per view).
    Returns True if anything was added."""
    from src.utils.romanization import generate_all

    added = False
    for line in lines:
        if "romanization" not in line:
            line["romanization"] = generate_all(line["thai"])
            added = True
    return added


def used_targets(lines: list[dict], candidates: list[dict]) -> list[str]:
    text = " ".join(l["thai"] for l in lines)
    return [c["thai"] for c in candidates if c["thai"] in text]


async def generate(
    db: AsyncSession,
    user_id: int,
    kind: str,
    scope: str,
    scope_id: int,
    rng: Optional[random.Random] = None,
) -> GeneratedText:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}")
    rng = rng or random.Random()

    label = await scope_label(db, scope, scope_id)
    if label is None:
        raise LookupError(f"{scope} {scope_id} not found")

    index = await reading_service.build_word_index(db, user_id)
    cards = await _scope_cards(db, scope, scope_id)
    candidates = pick_candidates(cards, index, rng)
    if len(candidates) < MIN_TARGETS:
        raise GenerationError(
            f"'{label}' needs at least {MIN_TARGETS} word cards to build a text around."
        )
    known = known_words(index, {c["thai"] for c in candidates}, rng)
    vocab_size = sum(1 for s in index.status.values() if s in ("known", "learning"))
    practice = {c["thai"] for c in candidates}
    calls: list[dict] = []

    # 1. Write
    data, model = await _ask_json(
        LLMTask.READING_GENERATION,
        prompts.GENERATION_SYSTEM,
        prompts.generation_prompt(kind, label, candidates, known, vocab_size),
        prompts.TEXT_SCHEMA,
        calls,
        "write",
    )
    lines = _clean_lines(data.get("lines", []))
    if len(lines) < MIN_LINES:
        raise GenerationError("The generated text came back too short or unreadable. Try again.")
    title = (data.get("title") or "").strip() or label

    # 2. Simplify once if too many words are beyond the learner
    hard = await asyncio.to_thread(hard_words, lines, index, practice)
    simplified: list[str] = []
    if len(hard) > MAX_HARD_WORDS:
        try:
            simpler, _ = await _ask_json(
                LLMTask.READING_GENERATION,
                prompts.GENERATION_SYSTEM,
                prompts.simplify_prompt(kind, title, lines, hard),
                prompts.TEXT_SCHEMA,
                calls,
                "simplify",
            )
            simpler_lines = _clean_lines(simpler.get("lines", []))
            if len(simpler_lines) >= MIN_LINES:
                still_hard = await asyncio.to_thread(hard_words, simpler_lines, index, practice)
                if len(still_hard) < len(hard):
                    simplified = [w for w in hard if w not in still_hard]
                    lines, hard = simpler_lines, still_hard
        except Exception as exc:
            logger.warning(f"reading simplify failed: {exc!r}")

    # 3. Check (whole text, then lines)
    try:
        result, _ = await _ask_json(
            LLMTask.READING_CHECK,
            prompts.CHECK_SYSTEM,
            prompts.check_prompt(kind, lines),
            prompts.CHECK_SCHEMA,
            calls,
            "check",
        )
        lines, check = apply_check(lines, result)
    except Exception as exc:  # the text is still useful unchecked
        logger.warning(f"reading check failed: {exc!r}")
        check = {"checked": False, "rewritten": False, "problem": "", "fixed": 0, "notes": []}
    check["simplified"] = simplified

    await asyncio.to_thread(_romanize_lines, lines)
    targets = used_targets(lines, candidates) or [c["thai"] for c in candidates[:MIN_TARGETS]]

    text = GeneratedText(
        user_id=user_id,
        kind=kind,
        scope=scope,
        scope_id=scope_id,
        title=title,
        lines=json.dumps(lines, ensure_ascii=False),
        target_words=json.dumps(targets, ensure_ascii=False),
        check=json.dumps(check, ensure_ascii=False),
        model=model,
        usage=json.dumps(calls),
    )
    db.add(text)
    await db.flush()
    return text


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _render_lines(text: GeneratedText, index: reading_service.WordIndex, prefs=None) -> list[dict]:
    from src.utils.romanization import resolve_effective

    rendered = []
    for line in json.loads(text.lines):
        schemes = line.pop("romanization", None) or {}
        out = {**line, "segments": reading_service.segment_line(line["thai"], index)}
        if prefs is not None:
            out["romanization"] = resolve_effective(
                {f"romanization_{k}": v for k, v in schemes.items()}, prefs
            )
        rendered.append(out)
    return rendered


async def get_text(db: AsyncSession, user_id: int, text_id: int) -> Optional[dict]:
    text = await db.get(GeneratedText, text_id)
    if text is None or text.user_id != user_id:
        return None
    from src.db.services.preferences_service import get_preferences

    stored = json.loads(text.lines)
    if await asyncio.to_thread(_romanize_lines, stored):  # texts saved before romanization existed
        text.lines = json.dumps(stored, ensure_ascii=False)
        await db.flush()
    prefs = await get_preferences(db)
    index = await reading_service.build_word_index(db, user_id)
    lines = _render_lines(text, index, prefs)
    return {
        "id": text.id,
        "kind": text.kind,
        "title": text.title,
        "scope": text.scope,
        "scope_id": text.scope_id,
        "scope_label": await scope_label(db, text.scope, text.scope_id),
        "target_words": json.loads(text.target_words),
        "check": json.loads(text.check) if text.check else None,
        "usage": pricing.summarize(json.loads(text.usage)) if text.usage else None,
        "created_at": text.created_at.isoformat(),
        "lines": lines,
        "stats": reading_service.score([l["segments"] for l in lines]),
    }


async def list_texts(db: AsyncSession, user_id: int) -> list[dict]:
    texts = (await db.scalars(
        select(GeneratedText).where(GeneratedText.user_id == user_id).order_by(GeneratedText.created_at.desc())
    )).all()
    if not texts:
        return []
    index = await reading_service.build_word_index(db, user_id)
    out = []
    for text in texts:
        lines = _render_lines(text, index)
        check = json.loads(text.check) if text.check else {}
        out.append({
            "id": text.id,
            "kind": text.kind,
            "title": text.title,
            "scope_label": await scope_label(db, text.scope, text.scope_id),
            "lines": len(lines),
            "checked": bool(check.get("checked")),
            "cost": pricing.summarize(json.loads(text.usage))["total_cost"] if text.usage else None,
            "created_at": text.created_at.isoformat(),
            **reading_service.score([l["segments"] for l in lines]),
        })
    return out


async def delete_text(db: AsyncSession, user_id: int, text_id: int) -> bool:
    text = await db.get(GeneratedText, text_id)
    if text is None or text.user_id != user_id:
        return False
    await db.delete(text)
    await db.flush()
    return True


async def list_sources(db: AsyncSession) -> dict:
    """Topics and chapters with enough cards to generate from."""
    from sqlalchemy import func

    topic_rows = (await db.execute(
        select(Topic.id, Topic.name, func.count(CardTopic.card_id))
        .join(CardTopic, CardTopic.topic_id == Topic.id)
        .group_by(Topic.id, Topic.name)
        .having(func.count(CardTopic.card_id) >= MIN_TARGETS)
        .order_by(Topic.name)
    )).all()
    upload_rows = (await db.execute(
        select(Card.source_upload_id, func.count(Card.id))
        .where(Card.source_upload_id.isnot(None))
        .group_by(Card.source_upload_id)
        .having(func.count(Card.id) >= MIN_TARGETS)
    )).all()
    chapters = []
    for upload_id, count in upload_rows:
        upload = await db.get(Upload, upload_id)
        if upload is None:
            continue
        parent = await db.get(Upload, upload.parent_upload_id) if upload.parent_upload_id else None
        chapters.append({
            "upload_id": upload_id,
            "title": reading_service.upload_title(upload, parent),
            "book_title": (parent.source_title or parent.filename) if parent else None,
            "card_count": count,
        })
    chapters.sort(key=lambda c: (c["book_title"] or "~", c["upload_id"]))
    return {
        "topics": [{"id": i, "name": n, "card_count": c} for i, n, c in topic_rows],
        "chapters": chapters,
    }
