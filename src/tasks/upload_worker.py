"""
In-process async worker for the upload pipeline.

A single long-lived task (started in lifespan) claims pending uploads from the
DB, processes them serially, and sleeps when idle. Serial processing is fine
for a single-user app and keeps the implementation simple.

Restart safety: on boot, call recover_interrupted() to reset any rows left in
status='processing' back to 'pending'. The worker will then re-claim and resume
from the last completed stage.

book_parent recovery:
  - 'splitting' / 'dispatching' → reset to pending so the stage reruns
  - 'awaiting_confirmation' → leave as-is (waiting for user to confirm)
"""
import asyncio
from datetime import datetime, timezone, timedelta
from loguru import logger
from sqlalchemy import select

from src.db.database import get_session_factory
from src.db.models.upload import Upload
from src.tasks.upload_tasks import process_upload

MAX_ATTEMPTS = 5
IDLE_SLEEP = 2.0  # seconds to sleep when no work is available

# Statuses the worker should pick up
ACTIONABLE_STATUSES = ("pending",)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def recover_interrupted(db) -> None:
    """
    Reset uploads stuck in status='processing' at startup.
    Because there is exactly one worker, any processing row at boot was
    interrupted mid-flight; reset it so the worker can resume from its stage.

    book_parent uploads in 'awaiting_confirmation' are left alone — they are
    intentionally paused until the user confirms the chapter map.
    """
    rows = list(await db.scalars(
        select(Upload).where(Upload.status == "processing")
    ))
    for upload in rows:
        logger.info(
            f"Startup: resetting interrupted upload {upload.id} "
            f"(kind={upload.kind}, stage={upload.stage}) to pending"
        )
        upload.status = "pending"
    if rows:
        await db.commit()


async def abandon_stale_uploads(db, older_than_hours: int = 24) -> None:
    """Mark uploads stuck in processing beyond the cutoff as failed."""
    cutoff = _utcnow() - timedelta(hours=older_than_hours)
    rows = list(await db.scalars(
        select(Upload).where(
            Upload.status == "processing",
            Upload.updated_at < cutoff,
        )
    ))
    for upload in rows:
        logger.warning(
            f"Abandoning stale upload {upload.id} "
            f"(stuck processing since {upload.updated_at})"
        )
        upload.status = "failed"
        upload.error_message = "Upload timed out after being stuck in processing"
    if rows:
        await db.commit()


async def run_worker_loop() -> None:
    """Long-lived worker loop. Runs as an asyncio task started from lifespan."""
    factory = get_session_factory()
    idle_ticks = 0

    while True:
        try:
            async with factory() as db:
                # Opportunistic stale-upload cleanup every ~5 minutes of idle
                if idle_ticks % 150 == 0:
                    await abandon_stale_uploads(db)

                upload = await _claim_next(db)

            if upload is None:
                idle_ticks += 1
                await asyncio.sleep(IDLE_SLEEP)
                continue

            idle_ticks = 0
            await _run_one(upload.id)

        except asyncio.CancelledError:
            logger.info("Upload worker loop cancelled — shutting down")
            return
        except Exception as exc:
            logger.exception(f"Upload worker loop error (will retry): {exc}")
            await asyncio.sleep(IDLE_SLEEP)


async def _claim_next(db) -> Upload | None:
    """
    Claim the next actionable upload (status='pending'), oldest first.
    Uploads in 'awaiting_confirmation' are intentionally skipped.
    Uploads exceeding MAX_ATTEMPTS are forced to failed and skipped.
    Returns None if nothing is available.
    """
    upload = await db.scalar(
        select(Upload)
        .where(Upload.status == "pending")
        .order_by(Upload.created_at)
        .limit(1)
    )

    if upload is None:
        return None

    if upload.attempts >= MAX_ATTEMPTS:
        logger.error(
            f"Upload {upload.id} exceeded max attempts ({MAX_ATTEMPTS}), forcing failed"
        )
        upload.status = "failed"
        upload.error_message = f"Exceeded maximum retry attempts ({MAX_ATTEMPTS})"
        await db.commit()
        return None

    upload.status = "processing"
    upload.attempts += 1
    await db.commit()
    return upload


async def _run_one(upload_id: int) -> None:
    """Open a fresh session, run the pipeline, handle failure."""
    factory = get_session_factory()
    async with factory() as db:
        upload = await db.get(Upload, upload_id)
        if upload is None:
            logger.error(f"Worker: upload {upload_id} vanished before processing")
            return

        try:
            await process_upload(db, upload)
        except Exception as exc:
            logger.exception(f"Upload {upload_id} failed at stage={upload.stage}: {exc}")
            upload = await db.get(Upload, upload_id)
            if upload:
                upload.status = "failed"
                upload.error_message = str(exc)
                await db.commit()
