"""
PaddleOCR wrapper — runs synchronously (call via asyncio.to_thread).
Thai language support requires paddleocr>=2.8 with lang='thai'.
"""
from typing import Optional
from .confidence import OcrResult

_ocr_instance = None


def _get_ocr():
    global _ocr_instance
    if _ocr_instance is None:
        try:
            from paddleocr import PaddleOCR
            _ocr_instance = PaddleOCR(lang="thai", use_angle_cls=True, show_log=False)
        except Exception:
            return None
    return _ocr_instance


def run_paddle_ocr(image_bytes: bytes) -> Optional[OcrResult]:
    """Returns OcrResult or None if PaddleOCR is not available."""
    import io
    import numpy as np
    from PIL import Image

    ocr = _get_ocr()
    if ocr is None:
        return None

    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.array(image)
        result = ocr.ocr(img_array, cls=True)

        if not result or not result[0]:
            return OcrResult(text="", engine_used="paddle", confidence=0.0)

        lines = []
        confidences = []
        for line in result[0]:
            if line and len(line) >= 2:
                text_info = line[1]
                if text_info and len(text_info) >= 2:
                    lines.append(str(text_info[0]))
                    confidences.append(float(text_info[1]))

        text = "\n".join(lines)
        mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return OcrResult(text=text, engine_used="paddle", confidence=mean_confidence)
    except Exception:
        return None
