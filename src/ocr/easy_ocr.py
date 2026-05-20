"""
EasyOCR wrapper — runs synchronously (call via asyncio.to_thread).
"""
from typing import Optional
from .confidence import OcrResult

_reader = None


def _get_reader():
    global _reader
    if _reader is None:
        try:
            import easyocr
            _reader = easyocr.Reader(["th", "en"], gpu=False, verbose=False)
        except ImportError:
            return None
    return _reader


def run_easy_ocr(image_bytes: bytes) -> Optional[OcrResult]:
    """Returns OcrResult or None if EasyOCR is not available."""
    import io
    import numpy as np
    from PIL import Image

    reader = _get_reader()
    if reader is None:
        return None

    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.array(image)
        result = reader.readtext(img_array, detail=1)

        if not result:
            return OcrResult(text="", engine_used="easy", confidence=0.0)

        lines = [item[1] for item in result]
        confidences = [item[2] for item in result]
        text = "\n".join(lines)
        mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return OcrResult(text=text, engine_used="easy", confidence=mean_confidence)
    except Exception:
        return None
