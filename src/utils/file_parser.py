"""
Converts uploaded files (PDF or image) into a list of image bytes for the OCR pipeline.
"""
import io
from typing import List, Tuple
from PIL import Image

MAX_DIMENSION = 2400  # px — resize larger images to reduce OCR memory overhead
JPEG_QUALITY = 90


def normalize_image(image_bytes: bytes) -> Tuple[bytes, str]:
    """Normalise an image to grayscale JPEG, resize if needed. Returns (bytes, media_type).

    Grayscale reduces file size ~3x vs RGB with no OCR quality loss (Thai text is
    black-on-white). Smaller bytes → fewer tokens when sent to Claude Vision fallback.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("L")  # grayscale

    # Resize if either dimension exceeds MAX_DIMENSION
    w, h = img.size
    if w > MAX_DIMENSION or h > MAX_DIMENSION:
        ratio = MAX_DIMENSION / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue(), "image/jpeg"


def pdf_to_images(pdf_bytes: bytes) -> List[Tuple[bytes, str]]:
    """
    Convert each page of a PDF to a JPEG image.
    Pages with extractable text are still converted to images so the OCR pipeline
    can be applied uniformly.
    """
    try:
        from pdf2image import convert_from_bytes
    except ImportError:
        raise RuntimeError("pdf2image is required for PDF support. Install with: pip install pdf2image")

    pil_images = convert_from_bytes(pdf_bytes, dpi=200, fmt="jpeg")
    result = []
    for img in pil_images:
        # Normalize each page
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY)
        normalized, media_type = normalize_image(buf.getvalue())
        result.append((normalized, media_type))
    return result


def prepare_file_for_ocr(file_bytes: bytes, filename: str) -> List[Tuple[bytes, str]]:
    """
    Returns a list of (image_bytes, media_type) tuples ready for the OCR pipeline.
    - PDFs → one tuple per page
    - Images → single tuple (normalized)
    """
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return pdf_to_images(file_bytes)
    else:
        # Treat as image
        normalized, media_type = normalize_image(file_bytes)
        return [(normalized, media_type)]
