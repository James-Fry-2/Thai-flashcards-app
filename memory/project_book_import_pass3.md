---
name: project-book-import-pass3
description: Pass 3 + Pass 3 Revision — Book import with ensemble chapter detection, boundary-based chapter_map, and full split-review UI
metadata:
  type: project
---

Pass 3 — Book Import completed (2026-07-21).
Pass 3 Revision (chapter detection + split review) completed (2026-07-23).

## Pass 3 — original

- **Migration** `j0k1l2m3n4o5_book_import.py` (chains from `i9j0k1l2m3n4`): adds `kind`, `parent_upload_id`, `chapter_map`, `requires_confirmation`, `source_title`, `chapter_label`, `section_label` to `uploads`.
- **Upload model** updated with self-referential `parent`/`children` relationship.
- **`src/utils/chapter_detect.py`** — `detect_chapter(text)` regex heading matcher + `scan_headings(pages)`.
- **`src/utils/file_parser.py`** — `extract_pdf_text_layer`, `extract_pdf_toc`, `slice_pdf`, `get_pdf_page_count` via PyMuPDF.
- **`src/tasks/upload_tasks.py`** — book_parent stages: `splitting → awaiting_confirmation → dispatching → complete`.
- **`src/api/routes/uploads.py`** — `POST /uploads/book`, `POST /uploads/{id}/confirm-split`, rollup GET endpoints.
- **Frontend** — `UploadPage.tsx` split into Single/Book mode; `useActiveUploads.ts` adds `awaiting_confirmation` to active set.

Key decisions: multi-file auto-dispatches; single PDF pauses for review; chapter_child runs unchanged Pass 1+2 pipeline.

---

## Pass 3 Revision — Ensemble detection + split-review UI

### What changed

**Schema (migration `k1l2m3n4o5p6_chapter_signals.py`):**
- New `page_signals` TEXT column on `uploads` (nullable JSON, per-page signal data from detection).
- `chapter_map` format changed from a list to `{"page_count": N, "boundaries": [...]}`.
  - `boundaries` entries: `{idx, page_start (1-indexed), title_en, title_th, include, confidence, signals[], source, child_upload_id}`.
  - `page_end` is **never stored** — always derived as `next_boundary.page_start - 1` (or `page_count` for last).
  - `source ∈ {auto, structure, user, example_match}`.
  - `include: false` → skipped span; no child upload, no LLM call.
- Legacy list format still supported in dispatch and GET endpoints (backwards compat for existing multi-file chapter_maps).

**Detection (`src/utils/chapter_signals.py`):**
- Tier 0 (structural, short-circuits heuristics when ≥2 entries found):
  1. `outline` — `doc.get_toc()`, finds best depth level.
  2. `toc_links` — hyperlinked TOC page (LINK_GOTO), extracts exact dest pages + titles from link rectangles.
  3. `page_labels` — numbering resets (roman→arabic = front matter end).
  4. `named_dests` — `doc.resolve_names()` (uncommon but free).
  5. `printed_toc` — regex `<title> ..... <num>`, verified with constant-offset calibration.
- Tier 1 (heuristic, single fitz pass):
  - `font_outlier`, `sparse_page`, `template_match` (image xref hash + layout fingerprint), `header_change`, `recto_start`, `lexical_hit`, `topic_shift` (optional, embedding-based).
  - Weighted score (all weights in Settings) above `chapter_boundary_threshold` → candidate boundary.
  - Title extraction: largest-font span → `title_en`; largest Thai-char span → `title_th`.
- All thresholds in Settings (`chapter_font_size_ratio`, `chapter_sparse_percentile`, `chapter_boundary_threshold`, etc.).
- Never raises — degrades to single whole-book boundary.
- `score_page_against_example(ex_sig, ca_sig)` for teach-by-example (layout_fingerprint + image Jaccard + char bucket).

**Settings additions:** `chapter_font_size_ratio`, `chapter_sparse_percentile`, `chapter_boundary_threshold`, `chapter_topic_shift_enabled/threshold`, `chapter_example_match_threshold`, all `chapter_weight_*`, `chapter_thumbnail_dpi`.

**API endpoints (new/updated in `src/api/routes/uploads.py`):**
- `GET /uploads/{id}/split` — boundaries with derived `page_end`, full `page_signals`, source_title, status.
- `PUT /uploads/{id}/split` — validate + normalise (ascending, 1..page_count, auto-insert page-1 front-matter if missing), save. Body `{"boundaries": [...], "warn_overwrite": bool}`.
- `POST /uploads/{id}/confirm-split` — updated to accept `{"boundaries": [...]}` (new) or `{"chapter_map": [...]}` (legacy). Resets `child_upload_id`, transitions to dispatching.
- `GET /uploads/{id}/pages/{n}/thumbnail` — fitz render at `chapter_thumbnail_dpi` DPI, cached under `<media>/uploads/<id>/thumbs/p_<nnnn>.jpg`.
- `POST /uploads/{id}/match-example` — body `{"page": N}`, reads persisted `page_signals`, scores all other pages via `score_page_against_example`, returns sorted proposals above `chapter_example_match_threshold`.
- All GET /uploads/{id} (book_parent) and /uploads/active rollup endpoints updated for new format; legacy list format auto-converted.

**Dispatching (`src/tasks/upload_tasks.py`):**
- `_parse_chapter_map_for_dispatch(raw)` returns `(entries, is_new_format)`.
- New format: `include:false` entries skipped; `page_end` derived from next boundary; pages 1-indexed → fitz 0-indexed conversion.
- Legacy format: old `page_start`/`page_end` (0-indexed) used directly.

**Frontend:**
- `types/index.ts`: new `ChapterBoundary`, `PageSignals`, `SplitData` types; `thumbnailUrl(uploadId, page)` helper; `Upload.chapter_map` now `ChapterBoundary[]`.
- `SplitReviewPage.tsx` (new, route `/uploads/:uploadId/split-review`):
  - Loads via `GET /uploads/{id}/split`.
  - Thumbnail filmstrip grouped by chapter with colored section markers.
  - Per-page: hover shows "+" to add boundary, "find similar" for teach-by-example.
  - Boundary editor table: include/skip toggle, page_start input, title_en/th inputs, confidence badge, signal badges.
  - Bulk controls: Include all, Skip all but first, Clear all.
  - Teach-by-example: click thumbnail → `POST match-example` → proposal panel with checkbox selection → Accept (add) or Replace.
  - Cost preview: "N chapters → N calls; M spans skipped".
  - Save (PUT) and Confirm (POST confirm-split) buttons.
  - Re-detect button warns before overwriting user/example_match boundaries.
- `UploadPage.tsx`: `awaiting_confirmation` state now shows "Review & confirm chapters" button → navigates to SplitReviewPage (replaces inline SplitReview editor).

### Key design invariants
- `page_end` never stored; always derived. Merge = delete a boundary; split = add one.
- Source provenance tracked: re-run detection warns before overwriting `user`/`example_match` boundaries.
- Nothing reaches the LLM until `confirm-split` is called.
- Multi-file imports use the legacy list format and still auto-dispatch.

**Why:** Lexical chapter detection (the old ladder) fails on books whose chapter openers have only display-font titles, sparse pages, and decorative borders — no "Chapter N" text. The ensemble of structural signals + heuristics + teach-by-example handles these books. The review UI gives the user a visual confirmation + correction workflow before any LLM cost is incurred.

**Optional follow-on (not yet implemented):** Setting-gated targeted LLM pass over candidate boundary pages only, for books where heuristics still fail.
