"""
EXPERIMENT (throwaway, read-only) — does a semantic-transparency score usable
signal for compound breakdowns?

Not wired into anything. Reads cards from the DB, writes a CSV + prints a
report, makes zero DB writes. Not imported by src/ or other scripts.

## What this measures

For every card with is_compound and a compound_breakdown of >=2 parts, score
how close the whole word's meaning is to its composed part glosses:

  Strategy A (averaged part glosses):
      score_A = cosine(embed(card.english), mean(embed(part.gloss)))
  Strategy B (joined gloss string):
      score_B = cosine(embed(card.english), embed(" ".join(part glosses)))
  Strategy C (Thai space, no glosses needed):
      score_C = cosine(embed(card.thai), mean(embed(part.thai)))

Parts with a null gloss are skipped for A/B (n_glossed is recorded so you can
see how often that happens); Strategy C always uses every part's Thai text.

Reuses the app's own embedding wrapper (src/utils/embeddings.py — same
sentence-transformers model embedding_service uses) so results transfer
directly to a real pipeline decision, without touching that service.

## Interpretation guide

- Is the signal usable? -> Do INCOHERENT cards cluster low and TRANSPARENT
  cards cluster high on the same strategy?
- Which strategy? -> Whichever of A/B/C gives the cleanest separation between
  the TRANSPARENT and INCOHERENT spot-check groups.
- Does it trap idioms? -> If IDIOMATIC scores land in the same low band as
  INCOHERENT, a hard suppress threshold is unsafe for this signal — it should
  drive *confidence/de-emphasis* or a *gloss-selection tiebreak* instead of
  outright suppression. If IDIOMATIC clearly separates from INCOHERENT (even
  if below TRANSPARENT), a soft threshold might be viable.
- Where would a threshold fall, and what would it wrongly catch? -> Read off
  the sorted CSV / the 15 lowest-score_A tail printed below and check by eye
  whether real junk or real idioms would be the first casualties.

## Explicitly NOT in scope here

Not wired into card creation. No stored transparency score. No migration.
No suppression/gating logic. This script only produces numbers to read.

## Run

    python scripts/experiment_transparency.py

Writes scripts/out/transparency.csv and prints the summary + spot-check to
stdout.
"""
import asyncio
import csv
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, "/app")

import numpy as np
from loguru import logger
from sqlalchemy import select

from src.db.database import get_session_factory
from src.db.models.card import Card
from src.utils.embeddings import embed_batch, cosine_similarity

OUT_DIR = Path(__file__).parent / "out"
OUT_CSV = OUT_DIR / "transparency.csv"

TRANSPARENT = ["น้ำแข็ง", "รถไฟ", "ห้องน้ำ", "สนามบิน"]        # should score HIGH
INCOHERENT = ["ประเทศ", "ครอบครัว", "อาหาร", "อะไร"]           # should score LOW (mis-segmented)
IDIOMATIC = ["น้ำใจ", "เข้าใจ", "น้ำตก"]                        # low but VALUABLE — the trap


async def _load_compound_cards() -> list[dict]:
    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(
            select(Card.thai, Card.english, Card.compound_breakdown)
            .where(Card.is_compound.is_(True))
            .where(Card.compound_breakdown.isnot(None))
            .order_by(Card.id)
        )
        rows = result.all()

    records = []
    for thai, english, breakdown_json in rows:
        try:
            parts = json.loads(breakdown_json)
        except (TypeError, ValueError):
            continue
        if not isinstance(parts, list) or len(parts) < 2:
            continue
        records.append({"thai": thai, "english": english, "parts": parts})
    return records


def _mean_vec(vecs: list[list[float]]) -> list[float]:
    return np.mean(np.array(vecs, dtype=np.float32), axis=0).tolist()


def main() -> None:
    records = asyncio.run(_load_compound_cards())
    logger.info(f"Loaded {len(records)} compound cards (is_compound + >=2 breakdown parts)")

    if not records:
        logger.warning("No compound cards found — nothing to score.")
        return

    # Collect every distinct string we'll need to embed, embed once, cache by text.
    texts: set[str] = set()
    for rec in records:
        texts.add(rec["english"])
        texts.add(rec["thai"])
        for part in rec["parts"]:
            if part.get("gloss"):
                texts.add(part["gloss"])
            if part.get("thai"):
                texts.add(part["thai"])
        glossed = [p["gloss"] for p in rec["parts"] if p.get("gloss")]
        if glossed:
            texts.add(" ".join(glossed))

    text_list = sorted(texts)
    logger.info(f"Embedding {len(text_list)} distinct strings...")
    vecs = embed_batch(text_list)
    cache: dict[str, list[float] | None] = dict(zip(text_list, vecs))

    if all(v is None for v in cache.values()):
        logger.error("Embedding model unavailable — every embed_batch result was None. Aborting.")
        return

    rows_out = []
    for rec in records:
        thai, english, parts = rec["thai"], rec["english"], rec["parts"]
        n_parts = len(parts)
        glossed_parts = [p for p in parts if p.get("gloss")]
        n_glossed = len(glossed_parts)

        whole_en_vec = cache.get(english)
        whole_thai_vec = cache.get(thai)

        score_a = score_b = score_c = None

        if whole_en_vec is not None and n_glossed > 0:
            gloss_vecs = [cache[p["gloss"]] for p in glossed_parts if cache.get(p["gloss"]) is not None]
            if gloss_vecs:
                score_a = cosine_similarity(whole_en_vec, _mean_vec(gloss_vecs))

            joined = " ".join(p["gloss"] for p in glossed_parts)
            joined_vec = cache.get(joined)
            if joined_vec is not None:
                score_b = cosine_similarity(whole_en_vec, joined_vec)

        if whole_thai_vec is not None:
            part_thai_vecs = [cache[p["thai"]] for p in parts if cache.get(p.get("thai")) is not None]
            if part_thai_vecs:
                score_c = cosine_similarity(whole_thai_vec, _mean_vec(part_thai_vecs))

        rows_out.append({
            "thai": thai,
            "english": english,
            "parts": "+".join(p.get("thai", "") for p in parts),
            "n_parts": n_parts,
            "n_glossed": n_glossed,
            "score_A": score_a,
            "score_B": score_b,
            "score_C": score_c,
        })

    skipped_a = sum(1 for r in rows_out if r["score_A"] is None)
    logger.info(f"score_A unavailable (no glossed parts / embed failure) for {skipped_a}/{len(rows_out)} cards")

    rows_out.sort(key=lambda r: r["score_A"] if r["score_A"] is not None else float("-inf"))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["thai", "english", "parts", "n_parts", "n_glossed", "score_A", "score_B", "score_C"])
        writer.writeheader()
        writer.writerows(rows_out)
    logger.info(f"Wrote {len(rows_out)} rows to {OUT_CSV}")

    _print_distribution(rows_out)
    _print_tails(rows_out)
    _print_spot_check(cache, records)
    _print_interpretation_prompts()


def _fmt(v) -> str:
    return f"{v:+.3f}" if v is not None else "  n/a"


def _print_distribution(rows_out: list[dict]) -> None:
    print("\n" + "=" * 78)
    print("SCORE DISTRIBUTIONS")
    print("=" * 78)
    for key in ("score_A", "score_B", "score_C"):
        vals = sorted(r[key] for r in rows_out if r[key] is not None)
        if not vals:
            print(f"{key}: no data")
            continue
        lo, hi = vals[0], vals[-1]
        p25 = statistics.quantiles(vals, n=4)[0] if len(vals) >= 4 else vals[0]
        med = statistics.median(vals)
        p75 = statistics.quantiles(vals, n=4)[2] if len(vals) >= 4 else vals[-1]
        print(f"\n{key}  (n={len(vals)})")
        print(f"  min={lo:+.3f}  p25={p25:+.3f}  median={med:+.3f}  p75={p75:+.3f}  max={hi:+.3f}")

        n_bins = 20
        span = (hi - lo) or 1e-9
        bins = [0] * n_bins
        for v in vals:
            idx = min(int((v - lo) / span * n_bins), n_bins - 1)
            bins[idx] += 1
        max_count = max(bins) or 1
        for i, count in enumerate(bins):
            bucket_lo = lo + span * i / n_bins
            bar = "#" * max(1, round(count / max_count * 40)) if count else ""
            print(f"    {bucket_lo:+.2f} | {bar} {count if count else ''}")


def _print_tails(rows_out: list[dict], n: int = 15) -> None:
    scored = [r for r in rows_out if r["score_A"] is not None]
    print("\n" + "=" * 78)
    print(f"LOWEST {n} by score_A  (candidates for junk / mis-segmentation)")
    print("=" * 78)
    for r in scored[:n]:
        print(f"  {_fmt(r['score_A'])}  {r['thai']:<14} {r['parts']:<24} -> {r['english']}")

    print("\n" + "=" * 78)
    print(f"HIGHEST {n} by score_A  (candidates for clean/transparent compounds)")
    print("=" * 78)
    for r in scored[-n:][::-1]:
        print(f"  {_fmt(r['score_A'])}  {r['thai']:<14} {r['parts']:<24} -> {r['english']}")


def _score_word(cache: dict, thai_word: str, records_by_thai: dict) -> dict | None:
    rec = records_by_thai.get(thai_word)
    if rec is None:
        return None
    parts = rec["parts"]
    glossed_parts = [p for p in parts if p.get("gloss")]

    whole_en_vec = cache.get(rec["english"])
    whole_thai_vec = cache.get(rec["thai"])

    score_a = score_b = score_c = None
    if whole_en_vec is not None and glossed_parts:
        gloss_vecs = [cache[p["gloss"]] for p in glossed_parts if cache.get(p["gloss"]) is not None]
        if gloss_vecs:
            score_a = cosine_similarity(whole_en_vec, _mean_vec(gloss_vecs))
        joined_vec = cache.get(" ".join(p["gloss"] for p in glossed_parts))
        if joined_vec is not None:
            score_b = cosine_similarity(whole_en_vec, joined_vec)
    if whole_thai_vec is not None:
        part_thai_vecs = [cache[p["thai"]] for p in parts if cache.get(p.get("thai")) is not None]
        if part_thai_vecs:
            score_c = cosine_similarity(whole_thai_vec, _mean_vec(part_thai_vecs))

    return {
        "thai": rec["thai"], "english": rec["english"],
        "parts": "+".join(p.get("thai", "") for p in parts),
        "score_A": score_a, "score_B": score_b, "score_C": score_c,
    }


def _print_spot_check(cache: dict, records: list[dict]) -> None:
    by_thai: dict = {}
    for r in records:
        by_thai.setdefault(r["thai"], r)  # first occurrence (lowest card id) wins

    print("\n" + "=" * 78)
    print("LABELLED SPOT-CHECK")
    print("=" * 78)
    for label, words in (
        ("TRANSPARENT (expect HIGH)", TRANSPARENT),
        ("INCOHERENT (expect LOW / mis-segmented)", INCOHERENT),
        ("IDIOMATIC (expect low but VALUABLE — the trap)", IDIOMATIC),
    ):
        print(f"\n{label}")
        for word in words:
            scored = _score_word(cache, word, by_thai)
            if scored is None:
                print(f"  {word:<12} -- not found among surfaced compound cards")
                continue
            print(
                f"  {word:<12} A={_fmt(scored['score_A'])}  B={_fmt(scored['score_B'])}  "
                f"C={_fmt(scored['score_C'])}   parts={scored['parts']:<20} -> {scored['english']}"
            )


def _print_interpretation_prompts() -> None:
    print("\n" + "=" * 78)
    print("READ THE SPOT-CHECK ABOVE AND ANSWER:")
    print("=" * 78)
    print("""
  1. Is the signal usable? Do INCOHERENT scores sit clearly below TRANSPARENT
     on the same strategy (A, B, or C)?
  2. Which strategy separates cleanest? Compare the A/B/C spread within each
     group above, and the histograms/tails printed earlier.
  3. Does it trap idioms? If IDIOMATIC scores land in the same band as
     INCOHERENT, don't use this signal to suppress breakdowns outright — use
     it only for confidence/de-emphasis or as a gloss-selection tiebreak.
     If IDIOMATIC clearly separates from INCOHERENT, a soft threshold may be
     viable.
  4. Where would a threshold fall? Look at the lowest-15 / highest-15 tails
     above — eyeball what a cutoff at, say, the p25 of score_A would catch,
     and whether that's mostly junk or includes real idioms.
""")


if __name__ == "__main__":
    main()
