"""
EXPERIMENT v3 (throwaway, read-only) — does requiring EVERY part to be
individually relevant (min-part cosine) fix the dominant-part confound v2
exposed in the additive-sum test?

Not wired into anything. Reads cards from the DB, writes a CSV + prints a
report, makes zero DB writes. Not imported by src/ or other scripts.

## Why this experiment (context from v1 and v2)

v1 (scripts/experiment_transparency.py) compared English gloss strings in a
sentence-transformers model — failed outright, sometimes inverted.

v2 (scripts/experiment_compositionality.py) tested additive Thai word2vec
arithmetic (Sum(v(part_i)) ~= v(whole)), ranked by nearest-neighbour position
among deck words. The additive property held far above chance in aggregate
(top-5 hit rate 63.3% vs ~0.9% chance) — a real positive result. But it
missed exactly the failure mode this whole investigation started from:
ประเทศ (ประ+เทศ) and อะไร (อะ+ไร) ranked *better* than most genuinely
transparent compounds, because one part alone (เทศ="country", ไร="what")
already resembles the whole word, so the vector sum is dominated by that one
part regardless of whether the other part (ประ, อะ) contributes anything.
The sum can't distinguish "both parts compose" from "one part carries it
alone."

This experiment tests the natural fix: instead of summing parts and asking
if the sum resembles the whole, score each part's INDIVIDUAL cosine to the
whole and take the MINIMUM — the weakest link. A compound should only count
as compositional if every part, not just its strongest part, is related to
the whole word's meaning.

## Why word-level word2vec (ltw2v), not fastText/thai2fit_wv

Same reasoning as v2: additive/geometric relevance signals require a
word-level space. fastText/thai2fit_wv build a word's vector partly from
character n-grams it contains, so a part sharing substrings with the whole
would look "relevant" purely from surface overlap, not composed meaning —
reproducing v1's confound in a new form. ltw2v (pythainlp.word_vector,
model_name="ltw2v") loads via gensim's KeyedVectors.load_word2vec_format — no
subword component.

## Method

For each is_compound card with a compound_breakdown of >=2 parts, using only
the Thai strings already stored (card.thai, part["thai"]) — no glosses, no
English. Skip (and count toward coverage) if the whole or any part is OOV.

  - per_part_cos: cos(v(part_i), v(whole)) for every part, individually.
  - min_part_cos = min(per_part_cos)  <- the primary metric: the weakest part.
  - mean_part_cos, max_part_cos, and gap = max_part_cos - min_part_cos (a
    large gap is the dominant-part signature: one part strongly resembles
    the whole, the other doesn't — exactly the ประเทศ/อะไร pattern).
  - sum_rank: v2's nearest-neighbour rank of the whole among deck words for
    Sum(v(part_i)), retained unchanged so v2 and v3 are directly comparable
    on the same cards without re-running v2.

## Interpretation guide

- Does min-part fix the dominant-part confound? The decisive test: do
  ประเทศ and อะไร (DOMINANT group — v2's known misses) fall BELOW the
  TRANSPARENT group on min_part_cos, while น้ำแข็ง/รถไฟ/ห้องน้ำ/สนามบิน stay
  up? If yes, min-part targets the real failure family v2 couldn't see.
- Does it catch the frequency-floor's blind spot? ครอบครัว is the key case:
  both parts (ครอบ, ครัว) are common, everyday words, so any frequency-based
  floor would wave it through — but they don't compose to "family," so a
  working min_part_cos should still rate it low. If min-part catches
  ครอบครัว, it's a genuine COMPLEMENT to a frequency floor (catches a
  different failure mode), not a duplicate of it — that's the actual ROI
  question this experiment exists to answer.
- Idioms (known limit, not a bug if it happens): น้ำใจ/น้ำตก/เข้าใจ may score
  low despite being valuable to learners — word2vec captures co-occurrence,
  not truth-conditional composition, so it can't tell "these words are used
  together idiomatically" from "these words don't relate." If idioms score
  low here, that's consistent with the known limit, not a new problem, and
  doesn't sink using this for the transparent-vs-mis-segmented split.
- Verdict framing: usable as a SECOND OPINION alongside a frequency floor
  only if it (a) drops ประเทศ/อะไร below the transparent group, AND (b)
  separately catches ครอบครัว (both-parts-common-but-non-composing) — the
  case a frequency floor structurally cannot catch. If either fails, mothball
  this too: a frequency floor + deny-set + Level-ranking stand on their own
  without this signal.

## Explicitly NOT in scope

No wiring, no stored score, no gating, no migration, no changes to
compound.py or any pipeline code. Diagnostic only.

## Run

    python scripts/experiment_perpart.py

Uses the same ltw2v corpus v2 downloaded (cached by pythainlp — fast after
the first run of ANY script that loaded it). Writes scripts/out/perpart.csv
and prints coverage + summary + spot-check to stdout.
"""
import asyncio
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")

import numpy as np
from loguru import logger
from sqlalchemy import select

from src.db.database import get_session_factory
from src.db.models.card import Card

OUT_DIR = Path(__file__).parent / "out"
OUT_CSV = OUT_DIR / "perpart.csv"

MODEL_NAME = "ltw2v"  # word-level word2vec only — see header for why fastText/thai2fit_wv are excluded

TRANSPARENT = ["น้ำแข็ง", "รถไฟ", "ห้องน้ำ", "สนามบิน"]   # both parts relevant -> min HIGH
DOMINANT = ["ประเทศ", "อะไร"]                              # one dead part -> min LOW (v2's sum-rank missed these)
INCOHERENT = ["ครอบครัว", "อาหาร"]                          # both parts weak -> min LOW (a frequency floor would miss ครอบครัว)
IDIOMATIC = ["น้ำใจ", "น้ำตก", "เข้าใจ"]                    # watch: may score low too (known limit, not a bug)


def _load_model():
    from pythainlp.word_vector.core import WordVector
    logger.info(f"Loading {MODEL_NAME} word2vec model (cached after first download by any experiment script)...")
    wv = WordVector(model_name=MODEL_NAME)
    model = wv.get_model()
    logger.info(f"Loaded {MODEL_NAME}: vocab={len(model.key_to_index)} dim={model.vector_size}")
    return model


async def _load_compound_cards() -> list[dict]:
    """Cards with is_compound + a >=2-part breakdown, Thai strings only (no gloss/english)."""
    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(
            select(Card.thai, Card.compound_breakdown)
            .where(Card.is_compound.is_(True))
            .where(Card.compound_breakdown.isnot(None))
            .order_by(Card.id)
        )
        rows = result.all()

    records = []
    for thai, breakdown_json in rows:
        try:
            parts = json.loads(breakdown_json)
        except (TypeError, ValueError):
            continue
        if not isinstance(parts, list) or len(parts) < 2:
            continue
        part_words = [p.get("thai") for p in parts if p.get("thai")]
        if len(part_words) < 2:
            continue
        records.append({"thai": thai, "parts": part_words})
    return records


async def _load_deck_vocab() -> list[str]:
    """Every distinct card.thai in the DB — candidate pool for sum_rank, kept
    identical to v2 so the column is directly comparable."""
    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(select(Card.thai).distinct())
        rows = result.all()
    return [r[0] for r in rows if r[0]]


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _cosine_to_matrix(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    q_norm = np.linalg.norm(query)
    if q_norm == 0:
        return np.zeros(matrix.shape[0], dtype=np.float32)
    m_norms = np.linalg.norm(matrix, axis=1)
    m_norms = np.where(m_norms == 0, 1e-9, m_norms)
    return (matrix @ query) / (m_norms * q_norm)


def _score(model, vocab_matrix: np.ndarray, word_to_row: dict, thai: str, parts: list[str]):
    """Return a score dict, or None if the whole or any part is OOV."""
    if thai not in model.key_to_index:
        return None
    part_vecs = []
    for p in parts:
        if p not in model.key_to_index:
            return None
        part_vecs.append(model[p])

    whole_vec = model[thai]
    per_part_cos = [_cosine(pv, whole_vec) for pv in part_vecs]
    min_part_cos = min(per_part_cos)
    mean_part_cos = sum(per_part_cos) / len(per_part_cos)
    max_part_cos = max(per_part_cos)
    gap = max_part_cos - min_part_cos

    composed_sum = np.sum(part_vecs, axis=0)
    sims = _cosine_to_matrix(composed_sum, vocab_matrix)
    order = np.argsort(-sims)
    target_row = word_to_row.get(thai)
    sum_rank = int(np.where(order == target_row)[0][0]) + 1 if target_row is not None else None

    return {
        "thai": thai,
        "parts": "+".join(parts),
        "n_parts": len(parts),
        "per_part_cos": ";".join(f"{c:.3f}" for c in per_part_cos),
        "min_part_cos": min_part_cos,
        "mean_part_cos": mean_part_cos,
        "max_part_cos": max_part_cos,
        "gap": gap,
        "sum_rank": sum_rank,
    }


def main() -> None:
    model = _load_model()
    records = asyncio.run(_load_compound_cards())
    deck_vocab = asyncio.run(_load_deck_vocab())
    logger.info(f"Loaded {len(records)} compound cards, {len(set(deck_vocab))} distinct deck words")

    vocab_words = [w for w in sorted(set(deck_vocab)) if w in model.key_to_index]
    logger.info(f"{len(vocab_words)}/{len(set(deck_vocab))} distinct deck words are present in {MODEL_NAME} vocab")
    vocab_matrix = np.array([model[w] for w in vocab_words], dtype=np.float32)
    word_to_row = {w: i for i, w in enumerate(vocab_words)}

    rows_out = []
    n_total = len(records)
    n_oov_skip = 0

    for rec in records:
        scored = _score(model, vocab_matrix, word_to_row, rec["thai"], rec["parts"])
        if scored is None:
            n_oov_skip += 1
            continue
        rows_out.append(scored)

    n_scored = len(rows_out)
    coverage_pct = (n_scored / n_total * 100) if n_total else 0.0

    print("\n" + "=" * 78)
    print("COVERAGE")
    print("=" * 78)
    print(f"  {n_total} compound cards total")
    print(f"  {n_scored} scored ({coverage_pct:.1f}%)")
    print(f"  {n_oov_skip} skipped — whole or a part word not in {MODEL_NAME} vocab")
    if coverage_pct < 50:
        print(
            "\n  ** COVERAGE BELOW 50% — treat any result below as INCONCLUSIVE. **\n"
            "  Instrument unfit for this vocabulary, not evidence the signal is absent."
        )

    if not rows_out:
        logger.warning("Nothing scored — no CSV written, no summary to print.")
        return

    rows_out.sort(key=lambda r: r["min_part_cos"])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["thai", "parts", "n_parts", "per_part_cos", "min_part_cos", "mean_part_cos", "max_part_cos", "gap", "sum_rank"],
        )
        writer.writeheader()
        writer.writerows(rows_out)
    logger.info(f"Wrote {len(rows_out)} rows to {OUT_CSV}")

    _print_distribution(rows_out)
    _print_tails(rows_out)
    _print_spot_check(model, vocab_matrix, word_to_row, records)
    _print_interpretation_prompts()


def _print_distribution(rows_out: list[dict]) -> None:
    vals = sorted(r["min_part_cos"] for r in rows_out)
    n = len(vals)
    lo, hi = vals[0], vals[-1]
    print("\n" + "=" * 78)
    print(f"min_part_cos DISTRIBUTION  (n={n})")
    print("=" * 78)
    print(f"  min={lo:+.3f}  p25={vals[n // 4]:+.3f}  median={vals[n // 2]:+.3f}  p75={vals[3 * n // 4]:+.3f}  max={hi:+.3f}")

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

    gaps = sorted(r["gap"] for r in rows_out)
    print(f"\n  gap (max_part_cos - min_part_cos) distribution — large gap = dominant-part signature:")
    print(f"  min={gaps[0]:+.3f}  median={gaps[n // 2]:+.3f}  max={gaps[-1]:+.3f}")


def _print_tails(rows_out: list[dict], n: int = 15) -> None:
    print("\n" + "=" * 78)
    print(f"LOWEST {n} by min_part_cos  (weakest-link candidates for junk / mis-segmentation)")
    print("=" * 78)
    for r in rows_out[:n]:
        print(f"  min={r['min_part_cos']:+.3f}  gap={r['gap']:+.3f}  sum_rank={r['sum_rank']!s:<5}  {r['thai']:<14} {r['parts']:<20} parts_cos=[{r['per_part_cos']}]")

    print("\n" + "=" * 78)
    print(f"HIGHEST {n} by min_part_cos  (both/all parts individually relevant)")
    print("=" * 78)
    for r in rows_out[-n:][::-1]:
        print(f"  min={r['min_part_cos']:+.3f}  gap={r['gap']:+.3f}  sum_rank={r['sum_rank']!s:<5}  {r['thai']:<14} {r['parts']:<20} parts_cos=[{r['per_part_cos']}]")


def _print_spot_check(model, vocab_matrix, word_to_row, records: list[dict]) -> None:
    by_thai: dict = {}
    for r in records:
        by_thai.setdefault(r["thai"], r)  # first occurrence (lowest card id) wins

    print("\n" + "=" * 78)
    print("LABELLED SPOT-CHECK")
    print("=" * 78)
    for label, words in (
        ("TRANSPARENT (expect min_part_cos HIGH — both parts relevant)", TRANSPARENT),
        ("DOMINANT (expect min_part_cos LOW — v2's sum-rank missed these)", DOMINANT),
        ("INCOHERENT (expect min_part_cos LOW — a frequency floor would miss ครอบครัว)", INCOHERENT),
        ("IDIOMATIC (watch: may score low too — known limit, not a bug)", IDIOMATIC),
    ):
        print(f"\n{label}")
        for word in words:
            rec = by_thai.get(word)
            if rec is None:
                print(f"  {word:<12} -- not found among surfaced compound cards")
                continue
            scored = _score(model, vocab_matrix, word_to_row, rec["thai"], rec["parts"])
            if scored is None:
                print(f"  {word:<12} -- OOV (whole or a part missing from {MODEL_NAME} vocab)")
                continue
            print(
                f"  {word:<12} min={scored['min_part_cos']:+.3f}  mean={scored['mean_part_cos']:+.3f}  "
                f"gap={scored['gap']:+.3f}  sum_rank={scored['sum_rank']!s:<5}  "
                f"parts={scored['parts']:<16} parts_cos=[{scored['per_part_cos']}]"
            )


def _print_interpretation_prompts() -> None:
    print("\n" + "=" * 78)
    print("READ THE RESULTS ABOVE IN THIS ORDER:")
    print("=" * 78)
    print("""
  1. DOMINANT group (ประเทศ, อะไร) — do they now fall BELOW the TRANSPARENT
     group on min_part_cos, while their sum_rank stays deceptively good?
     That would confirm min-part targets the exact failure v2's sum missed.
  2. ครอบครัว specifically — does it score LOW on min_part_cos despite both
     ครอบ and ครัว being common, everyday words a frequency floor would pass?
     That's the actual complement-vs-duplicate question for this signal.
  3. IDIOMATIC group — if these also score low, that's consistent with the
     known co-occurrence-vs-composition limit, not a new failure. It doesn't
     by itself sink the transparent-vs-mis-segmented use case.
  4. Verdict: usable as a second opinion ONLY if both (1) and (2) hold. If
     either fails, mothball this too — floor + deny-set + Level-ranking
     stand alone without it.
""")


if __name__ == "__main__":
    main()
