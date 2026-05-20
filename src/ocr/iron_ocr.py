"""
IronOCR sidecar client.

Calls the .NET IronOCR microservice (ironocr-service/) over HTTP.
Returns None if the service URL is not configured so the pipeline degrades gracefully.
"""
import base64
from typing import Optional

import httpx

from src.ocr.confidence import OcrResult
from src.config.settings import get_settings


async def run_iron_ocr(image_bytes: bytes) -> Optional[OcrResult]:
    """POST image bytes to the IronOCR sidecar and return an OcrResult, or None on failure."""
    settings = get_settings()
    url = settings.ironocr_url
    if not url:
        return None

    payload = {"imageBase64": base64.standard_b64encode(image_bytes).decode()}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{url}/ocr", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None

    text = data.get("text", "").strip()
    if not text:
        return None

    confidence = float(data.get("confidence", 0.0))
    return OcrResult(text=text, engine_used="iron_ocr", confidence=confidence)
