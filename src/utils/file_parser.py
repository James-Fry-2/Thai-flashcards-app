"""
Converts uploaded files (PDF or image) into a list of image bytes for the OCR pipeline.
Also provides text-layer extraction for digital PDFs (§6 — skips OCR on text pages).
"""
import io
from pathlib import Path
from typing import List, Optional, Tuple
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


def extract_pdf_text_layer(file_path: Path) -> List[str]:
    """
    Extract the text layer from each page of a PDF using PyMuPDF (fitz).
    Returns a list of strings — one per page — which may be empty for scanned pages.

    Used in the OCR stage to skip rasterise+OCR for pages with sufficient text
    (see pdf_text_min_chars in Settings).
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return []

    try:
        doc = fitz.open(str(file_path))
    except Exception:
        return []

    pages_text: List[str] = []
    for page in doc:
        try:
            text = page.get_text()
        except Exception:
            text = ""
        pages_text.append(text or "")
    doc.close()
    return pages_text


def extract_pdf_toc(file_path: Path) -> List[dict]:
    """
    Extract the PDF outline (Table of Contents) using PyMuPDF.
    Returns a list of {level, title, page} dicts (0-indexed page numbers).
    """
    try:
        import fitz
    except ImportError:
        return []

    try:
        doc = fitz.open(str(file_path))
        toc = doc.get_toc(simple=True)  # [[level, title, page], ...]
        doc.close()
    except Exception:
        return []

    return [{"level": entry[0], "title": entry[1], "page": max(0, entry[2] - 1)} for entry in toc]


def slice_pdf(src_path: Path, page_start: int, page_end: int, dst_path: Path) -> None:
    """
    Extract pages [page_start, page_end] (0-indexed, inclusive) from src_path
    into a new PDF at dst_path using PyMuPDF.
    """
    try:
        import fitz
    except ImportError:
        raise RuntimeError("PyMuPDF (fitz) is required for PDF slicing")

    src = fitz.open(str(src_path))
    dst = fitz.open()
    dst.insert_pdf(src, from_page=page_start, to_page=page_end)
    dst.save(str(dst_path))
    dst.close()
    src.close()


def get_pdf_page_count(file_path: Path) -> Optional[int]:
    """Return the total number of pages in a PDF, or None on error."""
    try:
        import fitz
        doc = fitz.open(str(file_path))
        count = doc.page_count
        doc.close()
        return count
    except Exception:
        return None


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
