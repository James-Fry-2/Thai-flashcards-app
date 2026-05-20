"""
OCR pipeline: PaddleOCR → EasyOCR → IronOCR → Claude Vision fallback.

All sync OCR methods are run via asyncio.to_thread() to avoid blocking the event loop.
IronOCR and Claude Vision are native async.
"""
import asyncio
import base64
import io
from PIL import Image
from src.ocr.confidence import OcrResult
from src.config.settings import get_settings

# Claude Vision charges by ~512×512 tile (~170 tokens each).
# Capping at 1024px means at most 4 tiles vs up to 25 tiles at 2400px.
_VISION_MAX_PX = 1024


def _resize_for_vision(image_bytes: bytes) -> bytes:
    """Shrink image to ≤1024px on longest side before sending to Claude Vision."""
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail((_VISION_MAX_PX, _VISION_MAX_PX), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


async def run_ocr_pipeline(image_bytes: bytes, media_type: str = "image/jpeg") -> OcrResult:
    settings = get_settings()
    threshold = settings.ocr_confidence_threshold

    # 1. Try PaddleOCR (sync → thread)
    from src.ocr.paddle_ocr import run_paddle_ocr
    result = await asyncio.to_thread(run_paddle_ocr, image_bytes)
    if result and result.confidence >= threshold:
        return result

    # 2. Try EasyOCR (sync → thread)
    from src.ocr.easy_ocr import run_easy_ocr
    result = await asyncio.to_thread(run_easy_ocr, image_bytes)
    if result and result.confidence >= threshold:
        return result

    # 3. Try IronOCR sidecar (no-op if IRONOCR_URL not set)
    from src.ocr.iron_ocr import run_iron_ocr
    result = await run_iron_ocr(image_bytes)
    if result and result.confidence >= threshold:
        return result

    # 4. Fall back to Claude Vision (resize first to minimise tile cost)
    return await _claude_vision_ocr(image_bytes, media_type)


async def _claude_vision_ocr(image_bytes: bytes, media_type: str) -> OcrResult:
    from src.llm.registry import get_provider, LLMTask
    from src.llm.prompts.ocr_fallback import OCR_PROMPT

    resized = _resize_for_vision(image_bytes)
    image_b64 = base64.standard_b64encode(resized).decode("utf-8")
    provider = get_provider(LLMTask.OCR_FALLBACK)
    response = await provider.complete_with_image(
        prompt=OCR_PROMPT,
        image_b64=image_b64,
        media_type=media_type,
    )
    return OcrResult(text=response.text, engine_used="claude_vision", confidence=1.0)
