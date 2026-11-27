"""Cached Thai text-to-speech.

get_audio(db, text, voice=..., speed=...) -> TTSResult
    Normalises and validates the text, then serves MEDIA_DIR/tts/<key>.mp3,
    synthesising it on a cache miss. The key is sha256(provider|voice|rate|text),
    so a phrase is paid for once per voice and speed. Each billed call is
    recorded in tts_usage.

card_audio(db, card, field, speed)       -> TTSResult   (+ a card_media row)
dialogue_voices(lines)                   -> {speaker: "female"|"male"}
usage_summary(db)                        -> chars / estimated cost
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.db.models.card import Card
from src.db.models.card_media import CardMedia
from src.db.models.tts_usage import TTSUsage
from src.tts import TTSError, TTSNotConfigured, get_tts_provider
from src.utils.text_integrity import find_invalid_chars, normalise_text

VoiceKind = Literal["female", "male"]
Speed = Literal["normal", "slow"]

_THAI_RE_RANGE = ("฀", "๿")
_locks: dict[str, asyncio.Lock] = {}

__all__ = [
    "TTSError", "TTSNotConfigured", "InvalidTTSText", "TTSResult",
    "get_audio", "cached_audio", "card_audio", "ensure_card_audio", "BatchResult",
    "dialogue_voices", "usage_summary",
]


class InvalidTTSText(ValueError):
    pass


@dataclass
class TTSResult:
    path: Path            # absolute file path
    storage_path: str     # relative to MEDIA_DIR
    cache_hit: bool
    chars: int


def clean_text(text: str, max_chars: Optional[int] = None) -> str:
    """NFC + strip zero-width chars + collapse whitespace; refuse corrupt,
    empty, non-Thai or overlong text before it reaches the paid API."""
    max_chars = max_chars or get_settings().tts_max_chars
    text, _ = normalise_text(text or "")
    text = " ".join(text.split())
    if not text:
        raise InvalidTTSText("text is empty")
    bad = find_invalid_chars(text)
    if bad:
        raise InvalidTTSText(f"text contains invalid character {bad[0][1]} at {bad[0][0]}")
    if not any(_THAI_RE_RANGE[0] <= ch <= _THAI_RE_RANGE[1] for ch in text):
        raise InvalidTTSText("text must contain Thai")
    if len(text) > max_chars:
        raise InvalidTTSText(f"text is longer than {max_chars} characters")
    return text


def _voice_name(kind: VoiceKind) -> str:
    s = get_settings()
    return s.tts_voice_male if kind == "male" else s.tts_voice_female


def _rate(speed: Speed) -> str:
    return get_settings().tts_slow_rate if speed == "slow" else "0%"


def cache_key(provider: str, voice: str, rate: str, text: str) -> str:
    return hashlib.sha256(f"{provider}|{voice}|{rate}|{text}".encode("utf-8")).hexdigest()


def _storage_path(key: str) -> str:
    return f"tts/{key[:2]}/{key}.mp3"


def _locate(text: str, voice: VoiceKind, speed: Speed) -> tuple[str, str, str, str, Path]:
    """(clean text, voice name, rate, cache key, absolute path) for a clip."""
    settings = get_settings()
    text = clean_text(text)
    voice_name, rate = _voice_name(voice), _rate(speed)
    key = cache_key(settings.tts_provider, voice_name, rate, text)
    return text, voice_name, rate, key, Path(settings.media_dir) / _storage_path(key)


def cached_audio(text: Optional[str], voice: VoiceKind = "female", speed: Speed = "normal") -> Optional[Path]:
    """Path of an already-generated clip, or None. Never calls the provider."""
    try:
        *_, path = _locate(text or "", voice, speed)
    except InvalidTTSText:
        return None
    return path if path.is_file() else None


async def _synthesize(text: str, voice_name: str, rate: str, key: str, path: Path) -> Optional[str]:
    """Write the clip to *path* unless it already exists. Returns the
    provider's name when a billed call was made, None when it was cached.
    No database access, so callers can run several at once."""
    if path.is_file():
        return None
    # One synthesis per key even when the same phrase is requested twice at once.
    lock = _locks.setdefault(key, asyncio.Lock())
    try:
        async with lock:
            if path.is_file():
                return None
            provider = get_tts_provider()  # raises TTSNotConfigured
            audio = await provider.synthesize(text, voice_name, rate)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{os.getpid()}.{id(lock)}.tmp")
            tmp.write_bytes(audio)
            os.replace(tmp, path)  # atomic: a reader never sees a half-written file
            return provider.name
    finally:
        if not lock.locked():
            _locks.pop(key, None)


async def get_audio(
    db: AsyncSession, text: str, voice: VoiceKind = "female", speed: Speed = "normal"
) -> TTSResult:
    text, voice_name, rate, key, path = _locate(text, voice, speed)
    provider_name = await _synthesize(text, voice_name, rate, key, path)
    if provider_name:
        db.add(TTSUsage(provider=provider_name, voice=voice_name, rate=rate, chars=len(text), cache_key=key))
        await db.flush()
    return TTSResult(path, _storage_path(key), provider_name is None, len(text))


async def _record_card_media(db: AsyncSession, rows: list[tuple[int, str, str]]) -> None:
    """Add card_media rows (card_id, storage_path, alt_text) that don't exist yet."""
    if not rows:
        return
    existing = set(
        (await db.execute(
            select(CardMedia.card_id, CardMedia.storage_path).where(
                CardMedia.media_type == "audio",
                CardMedia.card_id.in_({r[0] for r in rows}),
            )
        )).all()
    )
    for card_id, storage_path, alt in rows:
        if (card_id, storage_path) not in existing:
            existing.add((card_id, storage_path))
            db.add(CardMedia(card_id=card_id, media_type="audio", storage_path=storage_path, alt_text=alt))
    await db.flush()


async def card_audio(
    db: AsyncSession, card: Card, field: Literal["thai", "example"] = "thai", speed: Speed = "normal"
) -> TTSResult:
    text = card.thai if field == "thai" else card.example_thai
    if not text:
        raise InvalidTTSText(f"card has no {field} text")
    result = await get_audio(db, text, "female", speed)
    await _record_card_media(db, [(card.id, result.storage_path, f"{field}:{speed}")])
    return result


CardField = Literal["thai", "example"]


@dataclass
class BatchResult:
    paths: dict[tuple[int, str, str], Path]   # (card_id, field, speed) -> clip
    generated: int = 0    # billed calls made
    cached: int = 0       # already on disk
    missing: int = 0      # not on disk and not generated (generate=False)
    skipped: int = 0      # no speakable Thai (empty, not Thai, too long)
    failed: int = 0       # provider errors
    chars: int = 0        # characters sent to the provider
    to_generate_chars: int = 0  # characters a generate=True run would send


async def ensure_card_audio(
    db: AsyncSession,
    cards: list[Card],
    fields: tuple[CardField, ...] = ("thai", "example"),
    speeds: tuple[Speed, ...] = ("normal",),
    generate: bool = True,
    concurrency: int = 4,
    on_progress=None,
) -> BatchResult:
    """Make sure each card's audio exists. With generate=False only reports
    and collects what is already cached (free; used for estimates and the
    default Anki export). Provider calls run *concurrency* at a time; all
    database writes happen afterwards on *db*, one at a time.

    Raises TTSNotConfigured before doing any work if clips are missing,
    generate=True and no provider is set up."""
    result = BatchResult(paths={})
    jobs = []
    seen_keys: set[str] = set()
    for card in cards:
        for field in fields:
            text = card.thai if field == "thai" else card.example_thai
            if not text:
                continue
            for speed in speeds:
                try:
                    clean, voice_name, rate, key, path = _locate(text, "female", speed)
                except InvalidTTSText:
                    result.skipped += 1
                    continue
                job = (card.id, field, speed, clean, voice_name, rate, key, path)
                if path.is_file():
                    result.cached += 1
                    result.paths[(card.id, field, speed)] = path
                    jobs.append((job, False))
                else:
                    if key not in seen_keys:
                        result.to_generate_chars += len(clean)
                    seen_keys.add(key)
                    jobs.append((job, True))

    pending = [job for job, needs in jobs if needs]
    if not generate:
        result.missing = len(pending)
        return result
    if pending:
        get_tts_provider()  # fail fast with TTSNotConfigured

    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def run(job):
        nonlocal done
        card_id, field, speed, clean, voice_name, rate, key, path = job
        async with sem:
            try:
                name = await _synthesize(clean, voice_name, rate, key, path)
                outcome = (job, name, None)
            except TTSError as exc:
                outcome = (job, None, exc)
        done += 1
        if on_progress:
            on_progress(done, len(pending))
        return outcome

    outcomes = await asyncio.gather(*(run(j) for j in pending))
    for job, name, exc in outcomes:
        card_id, field, speed, clean, voice_name, rate, key, path = job
        if exc is not None:
            result.failed += 1
            continue
        result.paths[(card_id, field, speed)] = path
        if name:
            result.generated += 1
            result.chars += len(clean)
            db.add(TTSUsage(provider=name, voice=voice_name, rate=rate, chars=len(clean), cache_key=key))
        else:
            result.cached += 1  # another card had the same text

    await _record_card_media(db, [
        (card_id, _storage_path(key), f"{field}:{speed}")
        for (card_id, field, speed, _c, _v, _r, key, _p), _needs in jobs
        if (card_id, field, speed) in result.paths
    ])
    return result


_MALE_PARTICLES = ("ครับ", "ผม")
_FEMALE_PARTICLES = ("ค่ะ", "คะ", "ดิฉัน", "นะคะ")


def dialogue_voices(lines: list[dict]) -> dict[str, VoiceKind]:
    """Pick a voice per speaker from the polite particles they use (the
    generator ties particles to the speaker's gender). Speakers with no
    clear signal get whichever voice keeps the two speakers distinct."""
    order: list[str] = []
    score: dict[str, int] = {}
    for line in lines:
        speaker = (line.get("speaker") or "").strip()
        if not speaker:
            continue
        if speaker not in score:
            order.append(speaker)
            score[speaker] = 0
        thai = line.get("thai") or ""
        score[speaker] += sum(thai.count(p) for p in _MALE_PARTICLES)
        score[speaker] -= sum(thai.count(p) for p in _FEMALE_PARTICLES)

    voices: dict[str, VoiceKind] = {s: "male" for s in order if score[s] > 0}
    voices.update({s: "female" for s in order if score[s] < 0})
    for s in order:
        if s in voices:
            continue
        used = set(voices.values())
        voices[s] = "female" if "female" not in used else ("male" if "male" not in used else "female")
    return voices


async def usage_summary(db: AsyncSession) -> dict:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = await db.scalar(select(func.coalesce(func.sum(TTSUsage.chars), 0)))
    month = await db.scalar(
        select(func.coalesce(func.sum(TTSUsage.chars), 0)).where(TTSUsage.created_at >= month_start)
    )
    calls = await db.scalar(select(func.count(TTSUsage.id)))
    per_char = settings.tts_price_per_million_chars / 1_000_000
    return {
        "total_chars": int(total),
        "month_chars": int(month),
        "calls": int(calls),
        "total_cost": round(int(total) * per_char, 4),
        "month_cost": round(int(month) * per_char, 4),
    }
