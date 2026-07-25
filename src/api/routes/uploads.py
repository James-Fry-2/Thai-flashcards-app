import io
import json
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.config.settings import get_settings
from src.db.models.upload import Upload

router = APIRouter(prefix="/uploads", tags=["uploads"])

ALLOWED_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}

ACTIVE_STATUSES = ("pending", "processing", "awaiting_confirmation")


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _upload_dict(upload: Upload) -> dict:
    return {
        "id": upload.id,
        "filename": upload.filename,
        "kind": upload.kind,
        "parent_upload_id": upload.parent_upload_id,
        "status": upload.status,
        "stage": upload.stage,
        "deck_id": upload.deck_id,
        "source_title": upload.source_title,
        "chapter_label": upload.chapter_label,
        "section_label": upload.section_label,
        "cards_created": upload.cards_created,
        "total_pages": upload.total_pages,
        "pages_processed": upload.pages_processed,
        "attempts": upload.attempts,
        "ocr_engine_used": upload.ocr_engine_used,
        "ocr_confidence": upload.ocr_confidence,
        "error_message": upload.error_message,
        "created_at": upload.created_at.isoformat(),
    }


def _parse_chapter_map(raw: Optional[str]) -> dict:
    """Normalise stored chapter_map to the new dict format."""
    if not raw:
        return {"page_count": 0, "boundaries": []}
    data = json.loads(raw)
    if isinstance(data, list):
        # Legacy list format — convert to new boundary format (0-indexed → 1-indexed)
        boundaries = []
        for entry in data:
            boundaries.append({
                "idx": entry.get("idx", len(boundaries)),
                "page_start": entry.get("page_start", 0) + 1,
                "title_en": entry.get("chapter_label"),
                "title_th": None,
                "include": True,
                "confidence": 0.5,
                "signals": [],
                "source": "auto",
                "child_upload_id": entry.get("child_upload_id"),
            })
        return {"page_count": 0, "boundaries": boundaries}
    return data


def _derive_page_ends(boundaries: list, page_count: int) -> list:
    """Add a derived 'page_end' field to each boundary (never stored)."""
    result = []
    for i, b in enumerate(boundaries):
        end = (boundaries[i + 1]["page_start"] - 1
               if i + 1 < len(boundaries)
               else page_count)
        result.append({**b, "page_end": end})
    return result


async def _book_parent_detail(db: AsyncSession, upload: Upload) -> dict:
    """Build GET response for a book_parent: base dict + chapter_map + child rollup."""
    from src.db.services.card_service import get_upload_card_counts

    base = _upload_dict(upload)
    cm = _parse_chapter_map(upload.chapter_map)
    boundaries = cm.get("boundaries", [])
    page_count = cm.get("page_count", upload.total_pages or 0)

    child_ids = [b["child_upload_id"] for b in boundaries if b.get("child_upload_id")]
    children_map: dict[int, Upload] = {}
    if child_ids:
        rows = list(await db.scalars(select(Upload).where(Upload.id.in_(child_ids))))
        children_map = {c.id: c for c in rows}

    # Card counts and due counts per child upload (single aggregated query)
    child_counts = await get_upload_card_counts(db, child_ids) if child_ids else {}

    chapters_total = sum(1 for b in boundaries if b.get("include", True))
    chapters_complete = sum(
        1 for b in boundaries
        if b.get("include", True) and b.get("child_upload_id")
        and children_map.get(b["child_upload_id"])
        and children_map[b["child_upload_id"]].status == "done"
    )
    chapters_failed = sum(
        1 for b in boundaries
        if b.get("include", True) and b.get("child_upload_id")
        and children_map.get(b["child_upload_id"])
        and children_map[b["child_upload_id"]].status == "failed"
    )
    cards_created_total = sum(c.cards_created for c in children_map.values())

    with_ends = _derive_page_ends(boundaries, page_count)
    child_details = []
    for b in with_ends:
        cid = b.get("child_upload_id")
        child = children_map.get(cid) if cid else None
        counts = child_counts.get(cid, {}) if cid else {}
        child_details.append({
            **b,
            "status": child.status if child else None,
            "stage": child.stage if child else None,
            "cards_created": child.cards_created if child else 0,
            "card_count": counts.get("card_count", 0),
            "due_count": counts.get("due_count", 0),
        })

    base.update({
        "chapter_map": boundaries,
        "page_count": page_count,
        "chapters_total": chapters_total,
        "chapters_complete": chapters_complete,
        "chapters_failed": chapters_failed,
        "cards_created_total": cards_created_total,
        "children": child_details,
    })
    return base


async def _book_parent_active_summary(db: AsyncSession, upload: Upload) -> dict:
    cm = _parse_chapter_map(upload.chapter_map)
    boundaries = cm.get("boundaries", [])
    child_ids = [b["child_upload_id"] for b in boundaries if b.get("child_upload_id")]

    chapters_total = sum(1 for b in boundaries if b.get("include", True))
    chapters_complete = chapters_failed = cards_created_total = 0

    if child_ids:
        rows = list(await db.scalars(select(Upload).where(Upload.id.in_(child_ids))))
        for child in rows:
            if child.status == "done":
                chapters_complete += 1
            elif child.status == "failed":
                chapters_failed += 1
            cards_created_total += child.cards_created

    base = _upload_dict(upload)
    base.update({
        "chapter_map": boundaries,
        "chapters_total": chapters_total,
        "chapters_complete": chapters_complete,
        "chapters_failed": chapters_failed,
        "cards_created_total": cards_created_total,
    })
    return base


# ---------------------------------------------------------------------------
# Upload creation
# ---------------------------------------------------------------------------

@router.post("/", status_code=202)
async def create_upload(
    file: UploadFile = File(...),
    deck_id: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024

    contents = await file.read()
    if len(contents) > max_bytes:
        raise HTTPException(413, f"File exceeds {settings.max_upload_size_mb}MB limit")

    content_type = file.content_type or ""
    lower_name = (file.filename or "").lower()
    if content_type not in ALLOWED_TYPES and not any(
        lower_name.endswith(ext)
        for ext in [".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"]
    ):
        raise HTTPException(415, "Unsupported file type")

    file_type = "pdf" if lower_name.endswith(".pdf") else "image"

    upload = Upload(
        filename=file.filename or "upload",
        file_type=file_type,
        kind="single",
        deck_id=deck_id,
        status="pending",
        stage="queued",
    )
    db.add(upload)
    await db.flush()
    await db.commit()

    upload_dir = Path(settings.media_dir) / "uploads" / str(upload.id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / upload.filename).write_bytes(contents)

    return {"id": upload.id, "status": "pending", "filename": upload.filename}


@router.post("/book", status_code=202)
async def create_book_upload(
    files: list[UploadFile] = File(...),
    source_title: str = Form(...),
    deck_id: Optional[int] = Form(None),
    auto_dispatch: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    """
    Import a whole book (single PDF → split by chapter) or multiple PDFs
    (one child per file, no confirmation step).
    """
    settings = get_settings()
    max_bytes = settings.max_book_upload_size_mb * 1024 * 1024

    if not files:
        raise HTTPException(400, "At least one file is required")

    for f in files:
        lower_name = (f.filename or "").lower()
        if not lower_name.endswith(".pdf"):
            raise HTTPException(415, "Book import only accepts PDF files")

    is_single_pdf = len(files) == 1

    upload = Upload(
        filename=files[0].filename or "book.pdf",
        file_type="pdf",
        kind="book_parent",
        deck_id=deck_id,
        source_title=source_title,
        status="pending",
        stage="queued",
        requires_confirmation=(is_single_pdf and not auto_dispatch),
        chapter_map=None,
    )
    db.add(upload)
    await db.flush()
    await db.commit()

    upload_dir = Path(settings.media_dir) / "uploads" / str(upload.id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    total_bytes = 0
    for f in files:
        lower_name = (f.filename or "").lower()
        safe_name = Path(lower_name).name or f"file_{id(f)}.pdf"
        dst = upload_dir / safe_name
        written = 0
        with open(dst, "wb") as fh:
            while True:
                chunk = await f.read(1 << 20)
                if not chunk:
                    break
                written += len(chunk)
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise HTTPException(413, f"Total upload exceeds {settings.max_book_upload_size_mb}MB limit")
                fh.write(chunk)

    if not is_single_pdf:
        # Multi-file: build legacy chapter_map directly from the files
        chapter_map = []
        for i, f in enumerate(files):
            stem = Path(f.filename or f"file_{i + 1}").stem
            label = stem.replace("_", " ").replace("-", " ").strip()
            if not label or label.isdigit():
                label = f"Chapter {i + 1}"
            chapter_map.append({
                "idx": i,
                "chapter_label": label,
                "section_label": None,
                "page_start": 0,
                "page_end": -1,
                "child_upload_id": None,
                "source_filename": Path(f.filename or "").name,
            })
        upload.chapter_map = json.dumps(chapter_map)
        upload.requires_confirmation = False
        await db.commit()

    return {"id": upload.id, "kind": "book_parent", "status": "pending", "source_title": source_title}


# ---------------------------------------------------------------------------
# Book import list (all historical book_parent uploads)
# ---------------------------------------------------------------------------

@router.get("/books")
async def list_book_uploads(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Return all book_parent uploads (active and completed), newest first."""
    rows = list(await db.scalars(
        select(Upload)
        .where(Upload.kind == "book_parent")
        .order_by(Upload.created_at.desc())
        .limit(limit)
    ))
    return [await _book_parent_active_summary(db, u) for u in rows]


# ---------------------------------------------------------------------------
# Active upload list
# ---------------------------------------------------------------------------

@router.get("/active")
async def list_active_uploads(db: AsyncSession = Depends(get_db)):
    rows = list(await db.scalars(
        select(Upload)
        .where(Upload.status.in_(ACTIVE_STATUSES))
        .order_by(Upload.created_at.desc())
    ))
    result = []
    for u in rows:
        if u.kind == "chapter_child":
            continue
        if u.kind == "book_parent":
            result.append(await _book_parent_active_summary(db, u))
        else:
            result.append(_upload_dict(u))
    return result


# ---------------------------------------------------------------------------
# Single upload status
# ---------------------------------------------------------------------------

@router.get("/{upload_id}")
async def get_upload_status(upload_id: int, db: AsyncSession = Depends(get_db)):
    upload = await db.get(Upload, upload_id)
    if not upload:
        raise HTTPException(404, "Upload not found")
    if upload.kind == "book_parent":
        return await _book_parent_detail(db, upload)
    return _upload_dict(upload)


# ---------------------------------------------------------------------------
# Split review endpoints (§3, §4, §5)
# ---------------------------------------------------------------------------

@router.get("/{upload_id}/split")
async def get_split(upload_id: int, db: AsyncSession = Depends(get_db)):
    """Return the current chapter_map with derived page_ends and the page_signals summary."""
    upload = await db.get(Upload, upload_id)
    if not upload:
        raise HTTPException(404, "Upload not found")
    if upload.kind != "book_parent":
        raise HTTPException(409, "Not a book parent upload")

    cm = _parse_chapter_map(upload.chapter_map)
    boundaries = cm.get("boundaries", [])
    page_count = cm.get("page_count", upload.total_pages or 0)

    page_signals: dict = {}
    if upload.page_signals:
        try:
            page_signals = json.loads(upload.page_signals)
        except Exception:
            pass

    return {
        "id": upload_id,
        "page_count": page_count,
        "boundaries": _derive_page_ends(boundaries, page_count),
        "page_signals": page_signals,
        "source_title": upload.source_title,
        "stage": upload.stage,
        "status": upload.status,
    }


@router.put("/{upload_id}/split")
async def put_split(
    upload_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Save an edited boundary list.  Validates, normalises (ensures page 1 start,
    ascending order, renumbers idx) and persists. Idempotent.

    Body: {"boundaries": [...], "warn_overwrite": false}
    """
    upload = await db.get(Upload, upload_id)
    if not upload:
        raise HTTPException(404, "Upload not found")
    if upload.kind != "book_parent":
        raise HTTPException(409, "Not a book parent upload")

    incoming: list = body.get("boundaries")
    if not isinstance(incoming, list):
        raise HTTPException(422, "boundaries must be a list")

    cm = _parse_chapter_map(upload.chapter_map)
    page_count = cm.get("page_count", upload.total_pages or 0)

    # Warn if user edits would be lost (detection re-run scenario)
    if body.get("warn_overwrite", False):
        protected = {b["page_start"] for b in cm.get("boundaries", [])
                     if b.get("source") in ("user", "example_match")}
        incoming_starts = {b.get("page_start") for b in incoming}
        lost = protected - incoming_starts
        if lost:
            raise HTTPException(409, {
                "detail": "Re-run would discard user-edited boundaries",
                "protected_pages": sorted(lost),
            })

    # Validate and normalise
    validated = _validate_and_normalise_boundaries(incoming, page_count)

    cm["boundaries"] = validated
    upload.chapter_map = json.dumps(cm)
    await db.commit()

    return {
        "id": upload_id,
        "page_count": page_count,
        "boundaries": _derive_page_ends(validated, page_count),
    }


def _validate_and_normalise_boundaries(incoming: list, page_count: int) -> list:
    """
    Validate, sort and renumber boundaries.

    Rules:
    - page_start must be int in 1..page_count (or 1..∞ if page_count unknown)
    - Strictly ascending starts
    - Auto-insert a front-matter boundary at page 1 if not present
    - No duplicates
    """
    if not incoming:
        return [{
            "idx": 0,
            "page_start": 1,
            "title_en": "Full book",
            "title_th": None,
            "include": True,
            "confidence": 0.0,
            "signals": [],
            "source": "user",
            "child_upload_id": None,
        }]

    # Coerce and validate page_start
    clean = []
    seen_starts: set[int] = set()
    for entry in incoming:
        ps = entry.get("page_start")
        if not isinstance(ps, int) or ps < 1:
            raise HTTPException(422, f"page_start must be a positive integer, got {ps!r}")
        if page_count and ps > page_count:
            raise HTTPException(422, f"page_start {ps} exceeds page_count {page_count}")
        if ps in seen_starts:
            raise HTTPException(422, f"Duplicate page_start {ps}")
        seen_starts.add(ps)
        clean.append({
            "idx": 0,  # renumbered below
            "page_start": ps,
            "title_en": entry.get("title_en"),
            "title_th": entry.get("title_th"),
            "include": bool(entry.get("include", True)),
            "confidence": float(entry.get("confidence", 0.0)),
            "signals": list(entry.get("signals", [])),
            "source": entry.get("source", "user"),
            "child_upload_id": entry.get("child_upload_id"),
        })

    clean.sort(key=lambda b: b["page_start"])

    # Auto-insert leading front-matter boundary at page 1 if missing
    if clean[0]["page_start"] != 1:
        clean.insert(0, {
            "idx": 0,
            "page_start": 1,
            "title_en": "Front matter",
            "title_th": None,
            "include": False,
            "confidence": 0.0,
            "signals": [],
            "source": "auto",
            "child_upload_id": None,
        })

    # Renumber
    for i, b in enumerate(clean):
        b["idx"] = i

    return clean


@router.post("/{upload_id}/confirm-split")
async def confirm_split(
    upload_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Finalise the chapter map and transition the parent to dispatching.

    Body (new format):  {"boundaries": [...]}
    Body (legacy):      {"chapter_map": [...]}   — backwards compat

    Only include:true boundaries become chapter_child uploads.
    409 if not awaiting confirmation.
    """
    upload = await db.get(Upload, upload_id)
    if not upload:
        raise HTTPException(404, "Upload not found")
    if upload.kind != "book_parent":
        raise HTTPException(409, "Upload is not a book parent")
    if upload.stage != "awaiting_confirmation":
        raise HTTPException(409, f"Upload is not awaiting confirmation (stage={upload.stage})")

    # Accept both new {"boundaries": [...]} and legacy {"chapter_map": [...]} body shapes
    if "boundaries" in body:
        incoming = body["boundaries"]
    elif "chapter_map" in body:
        # Convert legacy format: page_start/page_end (0-indexed) → 1-indexed boundary format
        legacy = body["chapter_map"]
        if not isinstance(legacy, list):
            raise HTTPException(422, "chapter_map must be a list")
        incoming = []
        for e in legacy:
            incoming.append({
                "page_start": e.get("page_start", 0) + 1,
                "title_en": e.get("chapter_label"),
                "title_th": None,
                "include": True,
                "confidence": 0.0,
                "signals": [],
                "source": "user",
                "child_upload_id": None,
            })
    else:
        raise HTTPException(422, "Body must contain 'boundaries' or 'chapter_map'")

    if not isinstance(incoming, list) or not incoming:
        raise HTTPException(422, "boundaries must be a non-empty list")

    cm = _parse_chapter_map(upload.chapter_map)
    page_count = cm.get("page_count", upload.total_pages or 0)

    validated = _validate_and_normalise_boundaries(incoming, page_count)

    # Reset child_upload_id on all boundaries so dispatching creates fresh children
    for b in validated:
        b["child_upload_id"] = None

    cm["boundaries"] = validated
    upload.chapter_map = json.dumps(cm)
    upload.stage = "dispatching"
    upload.status = "pending"
    await db.commit()

    include_count = sum(1 for b in validated if b.get("include", True))
    return {
        "id": upload.id,
        "status": "pending",
        "stage": "dispatching",
        "chapters": include_count,
    }


# ---------------------------------------------------------------------------
# Page thumbnail (§3)
# ---------------------------------------------------------------------------

@router.get("/{upload_id}/pages/{page_num}/thumbnail")
async def get_page_thumbnail(
    upload_id: int,
    page_num: int,  # 1-indexed
    db: AsyncSession = Depends(get_db),
):
    """
    Render page page_num (1-indexed) as a low-DPI JPEG thumbnail.
    Cached on disk under <media_dir>/uploads/<id>/thumbs/p_<nnnn>.jpg.
    """
    upload = await db.get(Upload, upload_id)
    if not upload:
        raise HTTPException(404, "Upload not found")

    settings = get_settings()
    upload_dir = Path(settings.media_dir) / "uploads" / str(upload_id)
    thumb_dir = upload_dir / "thumbs"
    thumb_path = thumb_dir / f"p_{page_num:04d}.jpg"

    if thumb_path.exists():
        return Response(
            content=thumb_path.read_bytes(),
            media_type="image/jpeg",
            headers={"Cache-Control": "max-age=86400, immutable"},
        )

    # Locate the PDF
    pdf_files = list(upload_dir.glob("*.pdf")) + list(upload_dir.glob("*.PDF"))
    if not pdf_files:
        raise HTTPException(404, "PDF not found for this upload")
    pdf_path = pdf_files[0]

    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        page_count = len(doc)
        if page_num < 1 or page_num > page_count:
            doc.close()
            raise HTTPException(404, f"Page {page_num} out of range (1..{page_count})")

        page = doc[page_num - 1]  # 1-indexed → 0-indexed
        dpi = getattr(settings, "chapter_thumbnail_dpi", 50)
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
        doc.close()

        # Save to cache
        thumb_dir.mkdir(parents=True, exist_ok=True)
        jpeg_bytes = pix.tobytes("jpeg")
        thumb_path.write_bytes(jpeg_bytes)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Thumbnail render failed: {exc}") from exc

    return Response(
        content=jpeg_bytes,
        media_type="image/jpeg",
        headers={"Cache-Control": "max-age=86400, immutable"},
    )


# ---------------------------------------------------------------------------
# Teach-by-example (§4)
# ---------------------------------------------------------------------------

@router.post("/{upload_id}/match-example")
async def match_example(
    upload_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Given a single example page, find all pages with a similar structural signature.

    Body: {"page": int}  (1-indexed)

    Returns {"matches": [{"page": int, "score": float, "signals": [...]}]}
    sorted by score descending.  The caller accepts/rejects before any mutation.
    """
    upload = await db.get(Upload, upload_id)
    if not upload:
        raise HTTPException(404, "Upload not found")
    if upload.kind != "book_parent":
        raise HTTPException(409, "Not a book parent upload")

    example_page = body.get("page")
    if not isinstance(example_page, int) or example_page < 1:
        raise HTTPException(422, "page must be a positive integer")

    if not upload.page_signals:
        raise HTTPException(409, "No page signals available — re-run detection first")

    try:
        page_signals: dict = json.loads(upload.page_signals)
    except Exception:
        raise HTTPException(500, "Failed to parse page signals")

    example_key = str(example_page)
    if example_key not in page_signals:
        raise HTTPException(404, f"Page {example_page} not found in page signals")

    example_sig = page_signals[example_key]

    settings = get_settings()
    match_threshold = getattr(settings, "chapter_example_match_threshold", 0.75)

    from src.utils.chapter_signals import score_page_against_example

    matches = []
    for key, sig in page_signals.items():
        page_num = int(key)
        if page_num == example_page:
            continue
        score = score_page_against_example(example_sig, sig)
        if score >= match_threshold:
            fired = [k for k in ["font_outlier", "sparse_page", "template_match",
                                  "header_change", "lexical_hit"]
                     if sig.get(k)]
            matches.append({"page": page_num, "score": round(score, 3), "signals": fired})

    matches.sort(key=lambda m: -m["score"])
    return {"matches": matches}


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------

@router.post("/{upload_id}/retry")
async def retry_upload(upload_id: int, db: AsyncSession = Depends(get_db)):
    """Reset a failed upload so the worker re-claims and resumes it."""
    upload = await db.get(Upload, upload_id)
    if not upload:
        raise HTTPException(404, "Upload not found")
    if upload.status != "failed":
        raise HTTPException(409, f"Upload is not retryable (status={upload.status})")

    upload.status = "pending"
    upload.error_message = None
    await db.commit()
    return _upload_dict(upload)
