"""
EXPERIMENT v2 (throwaway, read-only) — does additive vector arithmetic on the
Thai parts (v(part1) + v(part2) ~= v(whole)) separate transparent compounds
from mis-segmented ones?

Not wired into anything. Reads cards from the DB, writes a CSV + prints a
report, makes zero DB writes. Not imported by src/ or other scripts.

## Why this is different from v1 (scripts/experiment_transparency.py)

v1 compared *English gloss strings* in a sentence-retrieval sentence-
transformers model and found the signal didn't separate transparent from
incoherent compounds (if anything, inverted) — see scripts/out/transparency.csv
and that experiment's writeup. This tests the actual textbook hypothesis
("water + hard ~= ice") directly: **Thai word vectors**, **additive**
arithmetic, in a **word2vec** space, scored by **nearest-neighbour rank**
rather than raw cosine magnitude (which v1 showed is not self-normalising —
absolute cosine values aren't comparable across words with different overall
embedding norms/frequency effects).

## Why word2vec (ltw2v), not fastText / thai2fit_wv

Additive analogies (king - man + woman ~= queen) are a property specifically
reported for word-level embeddings (word2vec / GloVe) trained via a
skip-gram/CBOW objective over whole-word contexts. fastText and PyThaiNLP's
default thai2fit_wv are *subword* models — a word's vector is built partly
from character n-grams it contains, so น้ำแข็ง would trivially look similar to
น้ำ and แข็ง just because it shares substrings with them, not because their
meanings compose. That's the exact "surface, not semantics" confound v1's
english-gloss test avoided in a different way (english glosses share no
characters with Thai parts) but is a live risk here since we're back to
Thai-vs-Thai. PyThaiNLP's `ltw2v` (pythainlp.word_vector, model_name="ltw2v")
is loaded via gensim's `KeyedVectors.load_word2vec_format` — a true word-level
word2vec table, no subword composition — so this risk doesn't apply here.
Confirmed via pythainlp.word_vector.core.WordVector.load_wordvector source.

## Method

For every card with is_compound and a compound_breakdown of >=2 parts, using
only the Thai strings already stored (card.thai, part["thai"]) — no glosses,
no English:

  - Look up each part's vector and the whole's vector. If any part or the
    whole is OOV in ltw2v, skip the card (counted toward coverage).
  - composed_sum = sum of part vectors (raw, unnormalised — matches the
    classic word2vec analogy convention); composed_mean is a secondary.
  - cos_sum / cos_mean: cosine(composed, whole) — reported but NOT the main
    test, since v1 showed raw cosine magnitude isn't comparable across words.
  - Nearest-neighbour rank (the real test): rank every OTHER word.thai in the
    deck (the candidate pool a real decomposition-guard would compare
    against — i.e. every distinct card.thai in this database, not just
    compounds) by cos(composed_sum, v(candidate)), and find the position of
    the compound's own true whole word in that ranking. rank=1 means
    part1+part2 retrieves its own whole ahead of every other word already in
    the deck. This is self-normalising: it doesn't matter that raw cosine
    magnitudes differ card to card, only relative ordering does.

## Interpretation guide

- Does the arithmetic hold at all? -> Look at the overall top-5 hit rate
  first. If part1+part2 rarely retrieves its own whole even for TRANSPARENT
  compounds, the additive property doesn't hold in this space for this data,
  and the approach is dead regardless of where a threshold is drawn.
- Does it separate transparent from mis-segmented? -> TRANSPARENT words
  should rank much better (lower rank number) than INCOHERENT ones. This is
  the actual question that matters for a decomposition-quality guard.
- The idiom caveat (expected, NOT a bug if it happens): IDIOMATIC compounds
  SHOULD rank poorly — น้ำใจ genuinely is not compositionally water+heart in
  vector space, same as it isn't in meaning. So even a working version of
  this test can never be a suppression gate for idioms; at best it separates
  transparent-vs-mis-segmented, and idioms would need a different treatment
  (or none) regardless of how well this signal performs.
- Coverage caveat: if a large fraction of cards are skipped for OOV, the
  result is "instrument unfit for this vocabulary," not "signal absent" —
  the next move in that case is an LLM-judge, not another embedding variant.

## Explicitly NOT in scope

No wiring, no stored score, no gating, no migration, no changes to
compound.py or any pipeline code. Diagnostic only — decide nothing until the
numbers are read.

## Run

    python scripts/experiment_compositionality.py

First run downloads the ltw2v corpus (~1.1GB, one-time, cached by pythainlp
under its corpus dir) — expect a multi-minute pause once, then fast on
subsequent runs. Writes scripts/out/compositionality.csv and prints
coverage + summary + spot-check to stdout.
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
OUT_CSV = OUT_DIR / "compositionality.csv"

# Word-level word2vec only — see header comment for why fastText/thai2fit_wv
# are excluded (subword leakage would reproduce v1's surface-similarity trap).
MODEL_NAME = "ltw2v"

TRANSPARENT = ["น้ำแข็ง", "รถไฟ", "ห้องน้ำ", "สนามบิน"]        # expect whole to rank HIGH (low rank #) for parts-sum
INCOHERENT = ["ประเทศ", "ครอบครัว", "อาหาร", "อะไร"]           # expect LOW rank (parts don't compose)
IDIOMATIC = ["น้ำใจ", "เข้าใจ", "น้ำตก"]                        # expect LOW rank — correctly non-compositional


def _load_model():
    from pythainlp.word_vector.core import WordVector
    logger.info(
        f"Loading {MODEL_NAME} word2vec model (first run downloads the corpus, "
        f"cached by pythainlp after that — may take a few minutes)..."
    )
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
    """Every distinct card.thai in the DB — the candidate pool for the nearest-
    neighbour rank test (not just compound whole-words): the realistic question
    is whether part1+part2 prefers its own whole over any other word already
    in the learner's deck, not just over other compounds."""
    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(select(Card.thai).distinct())
        rows = result.all()
    return [r[0] for r in rows if r[0]]


def _cosine_to_matrix(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    q_norm = np.linalg.norm(query)
    if q_norm == 0:
        return np.zeros(matrix.shape[0], dtype=np.float32)
    m_norms = np.linalg.norm(matrix, axis=1)
    m_norms = np.where(m_norms == 0, 1e-9, m_norms)
    return (matrix @ query) / (m_norms * q_norm)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _score(model, vocab_matrix: np.ndarray, vocab_words: list[str], word_to_row: dict, thai: str, parts: list[str]):
    """Return a score dict, or None if the whole or any part is OOV."""
    if thai not in model.key_to_index:
        return None
    part_vecs = []
    for p in parts:
        if p not in model.key_to_index:
            return None
        part_vecs.append(model[p])

    whole_vec = model[thai]
    composed_sum = np.sum(part_vecs, axis=0)
    composed_mean = np.mean(part_vecs, axis=0)

    cos_sum = _cosine(composed_sum, whole_vec)
    cos_mean = _cosine(composed_mean, whole_vec)

    sims = _cosine_to_matrix(composed_sum, vocab_matrix)
    order = np.argsort(-sims)
    target_row = word_to_row.get(thai)
    rank = int(np.where(order == target_row)[0][0]) + 1 if target_row is not None else None

    return {
        "thai": thai,
        "parts": "+".join(parts),
        "n_parts": len(parts),
        "cos_sum": cos_sum,
        "cos_mean": cos_mean,
        "rank": rank,
        "in_top5": bool(rank is not None and rank <= 5),
    }


def _global_neighbour_check(model, parts: list[str], whole: str, topn: int = 50):
    """Optional: does `whole` surface among the model's OWN global nearest
    neighbours of positive=parts (full ~730k vocab, not just the deck)?
    Only meaningful when `whole` is itself in the model vocabulary."""
    if whole not in model.key_to_index or any(p not in model.key_to_index for p in parts):
        return None
    try:
        neighbours = model.most_similar(positive=parts, topn=topn)
    except Exception:
        return None
    for i, (word, _sim) in enumerate(neighbours):
        if word == whole:
            return i + 1
    return None  # not in top-`topn` globally


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
        scored = _score(model, vocab_matrix, vocab_words, word_to_row, rec["thai"], rec["parts"])
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
            "  This means the instrument (this word2vec model's vocabulary) is a poor\n"
            "  fit for this deck's vocabulary, not that the compositionality signal is\n"
            "  absent. Don't read the separation numbers as a verdict on the hypothesis."
        )

    if not rows_out:
        logger.warning("Nothing scored — no CSV written, no summary to print.")
        return

    rows_out.sort(key=lambda r: r["rank"] if r["rank"] is not None else float("inf"))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["thai", "parts", "n_parts", "cos_sum", "cos_mean", "rank", "in_top5"])
        writer.writeheader()
        writer.writerows(rows_out)
    logger.info(f"Wrote {len(rows_out)} rows to {OUT_CSV}")

    _print_summary(rows_out, len(vocab_words))
    _print_tails(rows_out)
    _print_spot_check(model, vocab_matrix, vocab_words, word_to_row, records)
    _print_interpretation_prompts()


def _print_summary(rows_out: list[dict], n_candidates: int) -> None:
    n = len(rows_out)
    top1 = sum(1 for r in rows_out if r["rank"] == 1)
    top5 = sum(1 for r in rows_out if r["rank"] is not None and r["rank"] <= 5)
    top10 = sum(1 for r in rows_out if r["rank"] is not None and r["rank"] <= 10)
    ranks = [r["rank"] for r in rows_out if r["rank"] is not None]

    print("\n" + "=" * 78)
    print(f"HIT-RATE SUMMARY  (ranking against a pool of {n_candidates} deck words, n={n} scored compounds)")
    print("=" * 78)
    print(f"  top-1  hit rate: {top1}/{n} = {top1/n*100:.1f}%   (chance level ~= {100/n_candidates:.2f}%)")
    print(f"  top-5  hit rate: {top5}/{n} = {top5/n*100:.1f}%   (chance level ~= {500/n_candidates:.2f}%)")
    print(f"  top-10 hit rate: {top10}/{n} = {top10/n*100:.1f}%   (chance level ~= {1000/n_candidates:.2f}%)")
    if ranks:
        print(f"  rank: min={min(ranks)}  median={sorted(ranks)[len(ranks)//2]}  max={max(ranks)}")

    cos_vals = sorted(r["cos_sum"] for r in rows_out)
    lo, hi = cos_vals[0], cos_vals[-1]
    print(f"\n  cos_sum distribution: min={lo:+.3f}  median={cos_vals[len(cos_vals)//2]:+.3f}  max={hi:+.3f}")
    n_bins = 20
    span = (hi - lo) or 1e-9
    bins = [0] * n_bins
    for v in cos_vals:
        idx = min(int((v - lo) / span * n_bins), n_bins - 1)
        bins[idx] += 1
    max_count = max(bins) or 1
    for i, count in enumerate(bins):
        bucket_lo = lo + span * i / n_bins
        bar = "#" * max(1, round(count / max_count * 40)) if count else ""
        print(f"    {bucket_lo:+.2f} | {bar} {count if count else ''}")


def _print_tails(rows_out: list[dict], n: int = 15) -> None:
    print("\n" + "=" * 78)
    print(f"BEST {n} by rank  (part-sum retrieves its own whole word most precisely)")
    print("=" * 78)
    for r in rows_out[:n]:
        print(f"  rank={r['rank']:<5} cos_sum={r['cos_sum']:+.3f}  {r['thai']:<14} {r['parts']}")

    print("\n" + "=" * 78)
    print(f"WORST {n} by rank  (part-sum is furthest from its own whole word)")
    print("=" * 78)
    for r in rows_out[-n:][::-1]:
        rank_str = str(r["rank"]) if r["rank"] is not None else "n/a"
        print(f"  rank={rank_str:<5} cos_sum={r['cos_sum']:+.3f}  {r['thai']:<14} {r['parts']}")


def _print_spot_check(model, vocab_matrix, vocab_words, word_to_row, records: list[dict]) -> None:
    by_thai: dict = {}
    for r in records:
        by_thai.setdefault(r["thai"], r)  # first occurrence (lowest card id) wins

    print("\n" + "=" * 78)
    print("LABELLED SPOT-CHECK")
    print("=" * 78)
    for label, words in (
        ("TRANSPARENT (expect whole to rank HIGH, i.e. low rank #)", TRANSPARENT),
        ("INCOHERENT (expect LOW rank — parts don't compose)", INCOHERENT),
        ("IDIOMATIC (expect LOW rank — correctly non-compositional)", IDIOMATIC),
    ):
        print(f"\n{label}")
        for word in words:
            rec = by_thai.get(word)
            if rec is None:
                print(f"  {word:<12} -- not found among surfaced compound cards")
                continue
            scored = _score(model, vocab_matrix, vocab_words, word_to_row, rec["thai"], rec["parts"])
            if scored is None:
                print(f"  {word:<12} -- OOV (whole or a part missing from {MODEL_NAME} vocab)")
                continue
            global_rank = _global_neighbour_check(model, rec["parts"], word)
            global_str = f"global_top50_rank={global_rank}" if global_rank else "global_top50_rank=not found"
            print(
                f"  {word:<12} rank={scored['rank']:<5} cos_sum={scored['cos_sum']:+.3f} "
                f"cos_mean={scored['cos_mean']:+.3f}  parts={scored['parts']:<16} {global_str}"
            )


def _print_interpretation_prompts() -> None:
    print("\n" + "=" * 78)
    print("READ THE RESULTS ABOVE IN THIS ORDER:")
    print("=" * 78)
    print("""
  1. Coverage — if it's below 50%, stop here: the result is "instrument
     unfit," not "signal absent." The next move would be an LLM-judge, not
     another embedding variant.
  2. Overall top-5 hit rate — if part1+part2 rarely retrieves its own whole
     even in aggregate, the additive property doesn't hold in this space for
     this vocabulary, regardless of where a threshold would go.
  3. TRANSPARENT vs INCOHERENT rank separation in the spot-check — this is
     the one that actually matters for a decomposition-quality guard. Do
     TRANSPARENT words rank much better (lower number) than INCOHERENT ones?
  4. IDIOMATIC ranks — expected to be poor even if 1-3 all look good. A low
     rank here is not evidence against the signal; it just confirms this
     approach (even working) can't be an idiom-suppression gate, only a
     transparent-vs-mis-segmented split.
""")


if __name__ == "__main__":
    main()
