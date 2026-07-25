"""
Ensemble chapter-boundary detector for single-PDF book imports.

Opens the PDF once via fitz, computes all signals in that single pass, and
returns a chapter_map (boundary list) plus a page_signals dict for persisting.

Detection priority
------------------
Tier 0 — declared structure (check first; ≥2 entries short-circuits heuristics)
  1. PDF outline (get_toc)
  2. Hyperlinked TOC page (LINK_GOTO links on an early page)
  3. Page labels (roman→arabic numbering reset identifies front matter)
  4. Named destinations
  5. Printed TOC text (regex + offset calibration)

Tier 1 — heuristic signals (when Tier 0 yields nothing usable)
  font_outlier    largest/rare display font in top third of page
  sparse_page     char count below configurable percentile
  template_match  recurring image XObject or layout fingerprint
  header_change   running header text changed from previous page
  recto_start     odd 1-indexed page number (weak tiebreaker)
  lexical_hit     chapter heading regex (existing chapter_detect.py)
  topic_shift     embedding cosine-similarity local minimum (optional)

All thresholds and weights live in Settings — nothing hard-coded.

Never raises — degrades to a single whole-book boundary on any error.
"""

import hashlib
import re
import traceback
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

_THAI_RE = re.compile(r'[฀-๿]')
# TOC line: "Some title ........ 12" or "Title     12"
_TOC_LINE_RE = re.compile(r'^(.+?)\s*[.·\s]{2,}\s*(\d{1,4})\s*$')


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def detect_chapters(pdf_path: Path, settings) -> tuple[dict, dict]:
    """
    Main entry point — never raises.

    Returns
    -------
    chapter_map : dict
        {"page_count": N, "boundaries": [...]}  page_start is 1-indexed.
    page_signals : dict
        {"1": {char_count, font_outlier, …}, "2": …}  keys are 1-indexed strings.
    """
    try:
        return _detect(pdf_path, settings)
    except Exception:
        from loguru import logger
        logger.warning(f"Chapter detection error for {pdf_path}:\n{traceback.format_exc()}")
        try:
            import fitz
            doc = fitz.open(str(pdf_path))
            n = len(doc)
            doc.close()
        except Exception:
            n = 1
        return _whole_book(n), {}


# ---------------------------------------------------------------------------
# Signature scoring for teach-by-example
# ---------------------------------------------------------------------------

def score_page_against_example(example_signals: dict, candidate_signals: dict) -> float:
    """
    Score how similar candidate_signals is to example_signals.  Returns 0..1.
    Used by the match-example API endpoint (no re-parsing needed).
    """
    score = 0.0

    # Exact layout fingerprint match is the strongest signal
    if (example_signals.get("layout_fingerprint")
            and example_signals["layout_fingerprint"] == candidate_signals.get("layout_fingerprint")):
        score += 0.50

    # Image XObject Jaccard similarity
    ex_xrefs = set(example_signals.get("image_xrefs", []))
    ca_xrefs = set(candidate_signals.get("image_xrefs", []))
    if ex_xrefs or ca_xrefs:
        union = ex_xrefs | ca_xrefs
        if union:
            score += 0.35 * (len(ex_xrefs & ca_xrefs) / len(union))

    # Char-count bucket proximity (same sparsity class)
    ex_bucket = example_signals.get("char_count", 0) // 100
    ca_bucket = candidate_signals.get("char_count", 0) // 100
    if abs(ex_bucket - ca_bucket) <= 1:
        score += 0.15

    return min(1.0, score)


# ---------------------------------------------------------------------------
# Internal implementation
# ---------------------------------------------------------------------------

def _whole_book(page_count: int) -> dict:
    return {
        "page_count": page_count,
        "boundaries": [{
            "idx": 0,
            "page_start": 1,
            "title_en": "Full book",
            "title_th": None,
            "include": True,
            "confidence": 0.0,
            "signals": [],
            "source": "auto",
            "child_upload_id": None,
        }],
    }


def _detect(pdf_path: Path, settings) -> tuple[dict, dict]:
    import fitz
    doc = fitz.open(str(pdf_path))
    page_count = len(doc)

    if page_count == 0:
        doc.close()
        return _whole_book(0), {}

    # ---- Tier 0: declared structure ----------------------------------------
    t0 = _try_tier0(doc, page_count)
    if t0 is not None:
        doc.close()
        return t0, {}

    # ---- Single pass: collect per-page data for heuristics -----------------
    page_data = _collect_page_data(doc, page_count)
    doc.close()

    # ---- Tier 1: heuristic signals -----------------------------------------
    return _tier1(page_data, page_count, settings)


# ---------------------------------------------------------------------------
# Tier 0 helpers
# ---------------------------------------------------------------------------

def _try_tier0(doc, page_count: int) -> Optional[dict]:
    """Try each structural source.  Returns chapter_map or None."""
    for fn in (_from_outline, _from_toc_links, _from_page_labels,
               _from_named_dests, _from_printed_toc):
        try:
            result = fn(doc, page_count)
            if result is not None:
                return result
        except Exception:
            pass
    return None


def _boundary_entry(idx: int, page_start: int, title: str, include: bool,
                    signal_name: str) -> dict:
    th = title if _THAI_RE.search(title) else None
    en = title if not th else None
    return {
        "idx": idx,
        "page_start": page_start,
        "title_en": en,
        "title_th": th,
        "include": include,
        "confidence": 1.0,
        "signals": [signal_name],
        "source": "structure",
        "child_upload_id": None,
    }


def _finalize_boundaries(boundaries: list, page_count: int) -> dict:
    """Sort, renumber, ensure page 1 exists, return chapter_map."""
    if not boundaries:
        return _whole_book(page_count)
    boundaries.sort(key=lambda b: b["page_start"])
    # Auto-insert leading front-matter span if first boundary isn't page 1
    if boundaries[0]["page_start"] > 1:
        boundaries.insert(0, {
            "idx": 0,
            "page_start": 1,
            "title_en": "Front matter",
            "title_th": None,
            "include": False,
            "confidence": 1.0,
            "signals": [boundaries[0]["signals"][0] if boundaries[0]["signals"] else "auto"],
            "source": "structure",
            "child_upload_id": None,
        })
    for i, b in enumerate(boundaries):
        b["idx"] = i
    return {"page_count": page_count, "boundaries": boundaries}


def _from_outline(doc, page_count: int) -> Optional[dict]:
    """Build chapter_map from the PDF outline (get_toc)."""
    toc = doc.get_toc(simple=False)
    if not toc:
        return None

    # toc entries: [level, title, page_1indexed, dest]
    by_level: dict[int, list] = defaultdict(list)
    for entry in toc:
        level, title, page_1idx = entry[0], entry[1] or "", entry[2]
        by_level[level].append((title, max(1, page_1idx)))

    # Choose shallowest level with ≥2 entries spread across the document
    best_level = None
    for level in sorted(by_level.keys()):
        entries = by_level[level]
        if len(entries) >= 2:
            pages = [e[1] for e in entries]
            if max(pages) - min(pages) > 1:
                best_level = level
                break

    if best_level is None:
        return None

    entries = sorted(by_level[best_level], key=lambda e: e[1])
    boundaries = [_boundary_entry(i, page_1idx, title, True, "outline")
                  for i, (title, page_1idx) in enumerate(entries)]
    return _finalize_boundaries(boundaries, page_count)


def _from_toc_links(doc, page_count: int) -> Optional[dict]:
    """Find a hyperlinked TOC page and extract (dest_page, title) pairs."""
    import fitz

    max_toc_page = min(int(page_count * 0.2) + 1, 20)
    best_idx = -1
    best_count = 0

    for i in range(max_toc_page):
        links = [l for l in doc[i].get_links() if l.get("kind") == fitz.LINK_GOTO]
        if len(links) > best_count:
            best_count = len(links)
            best_idx = i

    if best_count < 2 or best_idx < 0:
        return None

    toc_page = doc[best_idx]
    links = [l for l in toc_page.get_links() if l.get("kind") == fitz.LINK_GOTO]

    seen: set[int] = set()
    boundaries = []
    for link in links:
        dest_0idx = link.get("page", -1)
        if dest_0idx < 0:
            continue
        dest_1idx = dest_0idx + 1
        if dest_1idx in seen:
            continue
        seen.add(dest_1idx)
        # Extract title text from the link's bounding rectangle
        rect = link.get("from")
        if rect:
            words = toc_page.get_text("words", clip=rect)
            title = " ".join(w[4] for w in words).strip()
        else:
            title = ""
        boundaries.append(_boundary_entry(0, dest_1idx, title, True, "toc_links"))

    if len(boundaries) < 2:
        return None
    return _finalize_boundaries(boundaries, page_count)


def _from_page_labels(doc, page_count: int) -> Optional[dict]:
    """Use page-label numbering resets to identify section boundaries."""
    try:
        labels = doc.get_page_labels()
    except AttributeError:
        return None

    if not labels or len(labels) < 2:
        return None

    boundaries = []
    for spec in labels:
        start_0idx = spec.get("startpage", 0)
        style = spec.get("style", "")
        # Each label restart is potentially a section boundary
        if start_0idx > 0:
            boundaries.append({
                "idx": 0,
                "page_start": start_0idx + 1,  # 0-indexed → 1-indexed
                "title_en": None,
                "title_th": None,
                "include": True,
                "confidence": 1.0,
                "signals": ["page_labels"],
                "source": "structure",
                "child_upload_id": None,
            })
            # Mark front matter as exclude if first section uses roman/none style
            if len(boundaries) == 1:
                first_style = labels[0].get("style", "")
                if first_style in ("r", "R", ""):
                    boundaries[0]["include"] = False
                    boundaries[0]["title_en"] = "Front matter"

    if len(boundaries) < 1:
        return None

    # Need at least 2 total boundaries (the implicit page-1 start + at least one restart)
    return _finalize_boundaries(boundaries, page_count)


def _from_named_dests(doc, page_count: int) -> Optional[dict]:
    """Extract chapter boundaries from named destinations (if supported)."""
    try:
        names = doc.resolve_names()
    except AttributeError:
        return None
    if not names:
        return None

    pages: list[int] = []
    for name, dest in names.items():
        if isinstance(dest, dict):
            p = dest.get("page", -1)
            if isinstance(p, int) and 0 <= p < page_count:
                pages.append(p + 1)  # 1-indexed
        elif isinstance(dest, int) and 0 <= dest < page_count:
            pages.append(dest + 1)

    pages = sorted(set(pages))
    if len(pages) < 2:
        return None

    # Only use if entries are spread across the document
    if max(pages) - min(pages) < 2:
        return None

    boundaries = [_boundary_entry(i, p, "", True, "named_dests") for i, p in enumerate(pages)]
    return _finalize_boundaries(boundaries, page_count)


def _from_printed_toc(doc, page_count: int) -> Optional[dict]:
    """Parse a printed TOC page for '<title> .... <page_number>' lines."""
    max_toc_page = min(int(page_count * 0.15) + 1, 15)

    best_entries: list[tuple[str, int]] = []

    for i in range(max_toc_page):
        text = doc[i].get_text()
        entries: list[tuple[str, int]] = []
        for line in text.splitlines():
            m = _TOC_LINE_RE.match(line.strip())
            if m:
                title = m.group(1).strip()
                num = int(m.group(2))
                if title and 1 <= num <= page_count + 50:
                    entries.append((title, num))
        if len(entries) > len(best_entries):
            best_entries = entries

    if len(best_entries) < 2:
        return None

    # Calibrate a constant offset between printed numbers and PDF 0-indexed pages
    best_offset = 0
    best_verified = 0
    for offset in range(-20, 21):
        verified = 0
        for title, printed_num in best_entries[:6]:
            pdf_0idx = printed_num - 1 + offset
            if 0 <= pdf_0idx < page_count:
                page_text = doc[pdf_0idx].get_text().lower()
                words = [w for w in title.split() if len(w) > 3]
                if words and any(w.lower() in page_text for w in words):
                    verified += 1
        if verified > best_verified:
            best_verified = verified
            best_offset = offset

    if best_verified < 2:
        return None

    boundaries = []
    seen: set[int] = set()
    for title, printed_num in best_entries:
        page_1idx = printed_num + best_offset  # printed → 1-indexed PDF
        if not (1 <= page_1idx <= page_count) or page_1idx in seen:
            continue
        seen.add(page_1idx)
        boundaries.append(_boundary_entry(0, page_1idx, title, True, "printed_toc"))

    if len(boundaries) < 2:
        return None
    return _finalize_boundaries(boundaries, page_count)


# ---------------------------------------------------------------------------
# Tier 1 — single-pass data collection
# ---------------------------------------------------------------------------

def _collect_page_data(doc, page_count: int) -> list[dict]:
    """Open the PDF once and collect per-page signal inputs."""
    pages = []
    for i in range(page_count):
        page = doc[i]
        try:
            text_dict = page.get_text("dict")
        except Exception:
            text_dict = {"blocks": []}

        # All text spans with position + font info
        spans = []
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    txt = span.get("text", "").strip()
                    if txt:
                        spans.append({
                            "text": txt,
                            "size": float(span.get("size", 0) or 0),
                            "font": span.get("font", "") or "",
                            "bbox": span.get("bbox"),
                        })

        full_text = page.get_text()
        char_count = len(full_text.strip())

        # First non-empty line (running header candidate)
        first_line = ""
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span.get("text", "").strip()
                    if t:
                        first_line = t
                        break
                if first_line:
                    break
            if first_line:
                break

        # Image XObject xrefs (unique per image in the doc)
        try:
            image_xrefs = [img[0] for img in page.get_images()]
        except Exception:
            image_xrefs = []

        try:
            page_height = float(page.rect.height)
        except Exception:
            page_height = 800.0

        pages.append({
            "idx": i,
            "char_count": char_count,
            "spans": spans,
            "first_line": first_line,
            "image_xrefs": image_xrefs,
            "page_height": page_height,
            "text": full_text,
        })
    return pages


# ---------------------------------------------------------------------------
# Tier 1 — scoring
# ---------------------------------------------------------------------------

def _tier1(page_data: list[dict], page_count: int, settings) -> tuple[dict, dict]:
    """Compute per-page heuristic signals and derive chapter boundaries."""
    if not page_data:
        return _whole_book(page_count), {}

    # --- Modal body font size ---
    font_size_freq: Counter = Counter()
    for pd in page_data:
        for span in pd["spans"]:
            bucket = round(span["size"] * 2) / 2  # round to 0.5pt
            font_size_freq[bucket] += len(span["text"])
    modal_size = font_size_freq.most_common(1)[0][0] if font_size_freq else 12.0

    font_size_ratio = getattr(settings, "chapter_font_size_ratio", 1.8)
    outlier_threshold = modal_size * font_size_ratio

    # --- Rare display fonts (appear on < 15% of pages) ---
    font_page_counter: Counter = Counter()
    for pd in page_data:
        for fname in {span["font"] for span in pd["spans"] if span["font"]}:
            font_page_counter[fname] += 1
    rare_font_threshold = max(1, int(page_count * 0.15))
    rare_fonts = {f for f, cnt in font_page_counter.items() if cnt <= rare_font_threshold}

    # --- Sparse-page threshold (10th percentile of char counts) ---
    sparse_pct = getattr(settings, "chapter_sparse_percentile", 10)
    char_counts = sorted(pd["char_count"] for pd in page_data)
    pct_idx = max(0, int(len(char_counts) * sparse_pct / 100) - 1)
    sparse_threshold = char_counts[pct_idx]

    # --- Image XObject frequency (rare = 2..30% of pages = template) ---
    xref_freq: Counter = Counter()
    for pd in page_data:
        for xref in set(pd["image_xrefs"]):
            xref_freq[xref] += 1
    max_tmpl_freq = max(2, int(page_count * 0.30))
    template_xrefs = {xref for xref, cnt in xref_freq.items()
                      if 2 <= cnt <= max_tmpl_freq}

    # --- Layout fingerprints ---
    def _fingerprint(pd: dict) -> str:
        fonts = frozenset(span["font"] for span in pd["spans"] if span["font"])
        bucket = pd["char_count"] // 100
        n_img = len(pd["image_xrefs"])
        raw = f"{sorted(fonts)}|{bucket}|{n_img}"
        return hashlib.md5(raw.encode()).hexdigest()[:8]

    fingerprints = [_fingerprint(pd) for pd in page_data]
    fp_freq: Counter = Counter(fingerprints)
    recurring_fps = {fp for fp, cnt in fp_freq.items() if 2 <= cnt <= max_tmpl_freq}

    # --- Optional topic-shift via embeddings ---
    topic_shift_flags = [False] * page_count
    if getattr(settings, "chapter_topic_shift_enabled", True) and page_count >= 3:
        try:
            from src.utils.embeddings import embed_batch, cosine_similarity
            texts = [pd["text"] for pd in page_data]
            vecs = embed_batch(texts)
            ts_threshold = getattr(settings, "chapter_topic_shift_threshold", 0.50)
            for i in range(len(vecs) - 1):
                v1, v2 = vecs[i], vecs[i + 1]
                if v1 and v2:
                    if cosine_similarity(v1, v2) < ts_threshold:
                        if i + 1 < page_count:
                            topic_shift_flags[i + 1] = True
        except Exception:
            pass

    # --- Signal weights ---
    W = {
        "font_outlier":   getattr(settings, "chapter_weight_font_outlier", 0.35),
        "sparse_page":    getattr(settings, "chapter_weight_sparse_page", 0.25),
        "template_match": getattr(settings, "chapter_weight_template_match", 0.30),
        "header_change":  getattr(settings, "chapter_weight_header_change", 0.20),
        "recto_start":    getattr(settings, "chapter_weight_recto_start", 0.05),
        "lexical_hit":    getattr(settings, "chapter_weight_lexical_hit", 0.40),
        "topic_shift":    getattr(settings, "chapter_weight_topic_shift", 0.20),
    }
    boundary_threshold = getattr(settings, "chapter_boundary_threshold", 0.45)

    from src.utils.chapter_detect import detect_chapter

    page_signals: dict[str, dict] = {}
    scores: list[float] = []
    headers = [pd["first_line"] for pd in page_data]

    for i, pd in enumerate(page_data):
        top_third = pd["page_height"] / 3

        # font_outlier: large span or rare display font in top third of page
        top_spans = [s for s in pd["spans"]
                     if s["bbox"] and (s["bbox"][1] <= top_third or s["bbox"][3] <= top_third)]
        max_top_size = max((s["size"] for s in top_spans), default=0.0)
        top_font_names = {s["font"] for s in top_spans if s["font"]}
        has_rare_font = bool(top_font_names & rare_fonts) and bool(top_spans)
        font_outlier = max_top_size >= outlier_threshold or has_rare_font

        # sparse_page
        sparse_page = pd["char_count"] <= sparse_threshold

        # template_match: rare shared image or recurring identical layout
        has_tmpl_img = bool(set(pd["image_xrefs"]) & template_xrefs)
        has_recur_fp = fingerprints[i] in recurring_fps
        template_match = has_tmpl_img or has_recur_fp

        # header_change: first line differs from previous page's first line
        header_change = False
        if i > 0 and pd["first_line"] and headers[i - 1]:
            curr = pd["first_line"][:60]
            prev = headers[i - 1][:60]
            header_change = curr != prev and len(curr) < 60

        # recto_start: 1-indexed page number is odd
        recto_start = (i % 2 == 0)  # fitz 0-index 0 → page 1 (odd)

        # lexical_hit
        lexical_hit = detect_chapter(pd["text"]) is not None

        # topic_shift
        topic_shift = topic_shift_flags[i]

        flags = {
            "font_outlier": font_outlier,
            "sparse_page": sparse_page,
            "template_match": template_match,
            "header_change": header_change,
            "recto_start": recto_start,
            "lexical_hit": lexical_hit,
            "topic_shift": topic_shift,
        }
        score = sum(W[k] * v for k, v in flags.items())
        scores.append(score)

        # Title extraction: largest font span → title_en; largest Thai span → title_th
        by_size = sorted(pd["spans"], key=lambda s: -s["size"])
        top_span_text = by_size[0]["text"] if by_size else None
        top_thai = next((s for s in by_size if _THAI_RE.search(s["text"])), None)

        page_signals[str(i + 1)] = {
            "char_count": pd["char_count"],
            "font_outlier": font_outlier,
            "sparse_page": sparse_page,
            "template_match": template_match,
            "header_change": header_change,
            "recto_start": recto_start,
            "lexical_hit": lexical_hit,
            "topic_shift": topic_shift,
            "heuristic_score": round(score, 4),
            "top_span_text": top_span_text,
            "top_thai_span_text": top_thai["text"] if top_thai else None,
            "image_xrefs": pd["image_xrefs"],
            "layout_fingerprint": fingerprints[i],
            "header_text": pd["first_line"],
        }

    # --- Select boundaries ---
    boundaries = _select_boundaries(scores, page_signals, page_count,
                                    boundary_threshold, scores)
    return {"page_count": page_count, "boundaries": boundaries}, page_signals


def _select_boundaries(scores: list[float], page_signals: dict,
                       page_count: int, threshold: float,
                       _scores_unused) -> list[dict]:
    """Convert per-page scores into a boundary list (always starts at page 1)."""
    SIGNAL_KEYS = ["font_outlier", "sparse_page", "template_match",
                   "header_change", "recto_start", "lexical_hit", "topic_shift"]

    # Collect candidate starts (page 1 always included)
    candidates = [1]
    for i, score in enumerate(scores):
        page_1idx = i + 1
        if page_1idx > 1 and score >= threshold:
            candidates.append(page_1idx)

    # Enforce minimum gap of 2 pages between boundaries
    filtered = [candidates[0]]
    for p in candidates[1:]:
        if p - filtered[-1] >= 2:
            filtered.append(p)

    boundaries = []
    for page_1idx in filtered:
        ps = page_signals.get(str(page_1idx), {})
        fired = [k for k in SIGNAL_KEYS if ps.get(k)]
        score_here = ps.get("heuristic_score", 0.0)

        title_en = ps.get("top_span_text")
        title_th = ps.get("top_thai_span_text")
        if title_en and _THAI_RE.search(title_en):
            if not title_th:
                title_th = title_en
            title_en = None

        # Page 1 with a low score and other pages follow → likely front matter
        is_auto_front = (
            page_1idx == 1
            and score_here < threshold
            and len(filtered) > 1
        )

        boundaries.append({
            "idx": len(boundaries),
            "page_start": page_1idx,
            "title_en": title_en,
            "title_th": title_th,
            "include": not is_auto_front,
            "confidence": round(score_here, 3),
            "signals": fired,
            "source": "auto",
            "child_upload_id": None,
        })

    if not boundaries:
        return [{
            "idx": 0,
            "page_start": 1,
            "title_en": "Full book",
            "title_th": None,
            "include": True,
            "confidence": 0.0,
            "signals": [],
            "source": "auto",
            "child_upload_id": None,
        }]

    return boundaries
