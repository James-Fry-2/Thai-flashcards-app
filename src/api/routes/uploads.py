from pathlib import Path
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.config.settings import get_settings
from src.db.models.upload import Upload
from src.tasks.upload_tasks import run_upload_pipeline

router = APIRouter(prefix="/uploads", tags=["uploads"])

ALLOWED_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}


@router.post("/", status_code=202)
async def create_upload(
    background_tasks: BackgroundTasks,
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
    # Allow application/octet-stream fallback, check extension
    lower_name = (file.filename or "").lower()
    if content_type not in ALLOWED_TYPES and not any(
        lower_name.endswith(ext) for ext in [".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"]
    ):
        raise HTTPException(415, "Unsupported file type")

    file_type = "pdf" if lower_name.endswith(".pdf") else "image"

    upload = Upload(
        filename=file.filename or "upload",
        file_type=file_type,
        deck_id=deck_id,
        status="pending",
    )
    db.add(upload)
    await db.flush()
    await db.commit()

    # Save file to disk before handing off to background task
    upload_dir = Path(settings.media_dir) / "uploads" / str(upload.id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / upload.filename).write_bytes(contents)

    background_tasks.add_task(run_upload_pipeline, upload.id)

    return {"id": upload.id, "status": "pending", "filename": upload.filename}


@router.get("/{upload_id}")
async def get_upload_status(upload_id: int, db: AsyncSession = Depends(get_db)):
    upload = await db.get(Upload, upload_id)
    if not upload:
        raise HTTPException(404, "Upload not found")
    return {
        "id": upload.id,
        "filename": upload.filename,
        "status": upload.status,
        "deck_id": upload.deck_id,
        "cards_created": upload.cards_created,
        "ocr_engine_used": upload.ocr_engine_used,
        "ocr_confidence": upload.ocr_confidence,
        "error_message": upload.error_message,
        "created_at": upload.created_at.isoformat(),
    }
