#!/usr/bin/env python3
"""
Quick smoke-test for the IronOCR sidecar.

Usage:
    # Image file:
    python scripts/test_ironocr.py path/to/image.jpg

    # PDF (each page is sent separately):
    python scripts/test_ironocr.py path/to/notes.pdf

    # Custom sidecar URL (default: http://localhost:5050):
    python scripts/test_ironocr.py path/to/notes.pdf --url http://localhost:5050
"""
import argparse
import base64
import io
import sys
from pathlib import Path

import httpx
from PIL import Image


def _image_to_jpeg(img: Image.Image) -> bytes:
    img = img.convert("L")          # grayscale — matches pipeline.py
    img.thumbnail((2400, 2400), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _load_pages(path: Path) -> list[tuple[int, bytes]]:
    """Return a list of (page_number, jpeg_bytes) tuples."""
    if path.suffix.lower() == ".pdf":
        import fitz  # pymupdf — no system poppler required
        doc = fitz.open(str(path))
        pages = []
        for i, page in enumerate(doc):
            mat = fitz.Matrix(200 / 72, 200 / 72)  # 200 DPI
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
            img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
            pages.append((i + 1, _image_to_jpeg(img)))
        return pages
    else:
        img = Image.open(path)
        return [(1, _image_to_jpeg(img))]


def ocr_page(url: str, jpeg_bytes: bytes) -> dict:
    b64 = base64.standard_b64encode(jpeg_bytes).decode()
    resp = httpx.post(f"{url}/ocr", json={"imageBase64": b64}, timeout=60.0)
    resp.raise_for_status()
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description="Test the IronOCR sidecar.")
    parser.add_argument("file", type=Path, help="PDF or image file to OCR")
    parser.add_argument("--url", default="http://localhost:5050", help="Sidecar base URL")
    args = parser.parse_args()

    if not args.file.exists():
        print(f"File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    # Health check
    try:
        health = httpx.get(f"{args.url}/health", timeout=5.0)
        health.raise_for_status()
        print(f"Sidecar healthy at {args.url}\n")
    except Exception as e:
        print(f"Sidecar not reachable at {args.url}: {e}", file=sys.stderr)
        print("Start it with:  docker compose up ironocr -d", file=sys.stderr)
        sys.exit(1)

    pages = _load_pages(args.file)
    print(f"Processing {len(pages)} page(s) from {args.file.name}\n{'─' * 60}")

    for page_num, jpeg_bytes in pages:
        kb = len(jpeg_bytes) / 1024
        print(f"\n[Page {page_num}]  ({kb:.0f} KB sent)")
        result = ocr_page(args.url, jpeg_bytes)
        confidence = result.get("confidence", 0)
        text = result.get("text", "").strip()
        print(f"Confidence: {confidence:.2%}")
        print(f"Text:\n{text or '(empty)'}")

    print(f"\n{'─' * 60}")
    print("Done.")


if __name__ == "__main__":
    main()
