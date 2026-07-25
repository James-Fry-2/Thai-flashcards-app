---
name: project-compound-breakdown
description: Compound breakdown hint (Level 1) — deterministic dictionary segmentation + gloss ladder, stored as derived JSON field
metadata:
  type: project
---

Implemented Compound breakdown hint (Level 1). Deterministic dictionary maximal-matching segmentation + gloss ladder (own cards → OMW wordnet → optional LLM), stored as derived JSON field on cards.

**Why:** Learning hint showing transparent compound structure (น้ำแข็ง → น้ำ water + แข็ง hard) at card creation, no LLM on hot path by default.

**How to apply:** Level 2 (promote constituents to linked cards via a new "constituent" link type, enabling a morpheme graph) is the natural follow-on; `is_compound` and the stored parts are the substrate it builds on.

## Key files
- `src/utils/compound.py` — `decompose()`, `resolve_glosses()`, `compute_compound_breakdown()`
- `alembic/versions/l2m3n4o5p6q7_compound_breakdown.py` — migration chained from k1l2m3n4o5p6
- `src/db/models/card.py` — `compound_breakdown` (Text/JSON), `is_compound` (Boolean) added
- `src/db/services/card_service.py` — `compute_compound_breakdown()` called in `create_card()`
- `src/api/routes/cards.py` — `_card_dict()` includes both fields
- `src/api/routes/review.py` — `_build_card_payload()` includes both fields
- `scripts/backfill_compound_breakdown.py` — idempotent backfill with `--dry-run`, `--batch-size`, `--with-llm`
- `tests/test_compound.py` — unit tests for decompose(), resolve_glosses(), surface rule
- `frontend/src/types/index.ts` — `CompoundPart` interface, `is_compound`/`compound_breakdown` on `Card`
- `frontend/src/components/CardDetailDrawer.tsx` — `BreakdownSection` (amber chips, shown below Script Analysis)
- `frontend/src/components/FlashCard.tsx` — `CompoundHint` (muted text, answer side only)

## Algorithm
- Minimum-parts DP over `pythainlp.corpus.thai_words()` frozenset; excludes whole-word self-match so น้ำแข็ง → [น้ำ, แข็ง] even when น้ำแข็ง is in the corpus.
- Surface rule: breakdown stored only when ≥1 part has a resolved gloss; is_compound=True even when no gloss surfaced.
- LLM fallback: `compound_gloss_llm_fallback` setting (default False); backfill `--with-llm` flag for one-time enrichment.
- Lexicon: OMW Thai (CC-BY 4.0) via `pythainlp.corpus.wordnet`.
