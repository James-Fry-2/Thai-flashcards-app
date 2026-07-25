"""
Detect chapter/section headings in OCR'd or extracted text.

Used by the book-import splitting ladder (TOC → heading scan → whole-book fallback)
and the Pass 2 chapter-topic categorization stage.
"""
import re
from typing import Optional

# Matches common chapter heading patterns at the start of a line.
# Groups: (1) optional chapter word, (2) number/numeral/letter, (3) optional title text
_HEADING_RE = re.compile(
    r"""
    ^
    (?:
        # "Chapter 1", "Chapter One", "บทที่ 1", "ตอนที่ 2", etc.
        (?:chapter|bab|bölüm|chapitre|kapitel|chapter|บทที่|ตอนที่|บท)\s*
        (?P<chapter_num>[0-9]+|[ivxlcdmIVXLCDM]+|[a-zA-Z]+)
        (?:\s*[:\-–—.]\s*|\s+)
        (?P<chapter_title>.+)?
    |
        # "1.", "1 ", "1 -", "I.", "A." at the very start (bare numbered heading)
        (?P<bare_num>[0-9]{1,3}|[ivxlIVX]{1,6}|[A-Z])
        [.)\s]\s+
        (?P<bare_title>[A-ZÀ-Ö฀-๿].{2,})
    )
    """,
    re.VERBOSE | re.IGNORECASE | re.MULTILINE,
)


def detect_chapter(text: str) -> Optional[str]:
    """
    Return the detected chapter heading from the first non-empty line of ``text``,
    or None if no heading is found.

    The returned string is the full matched heading line (stripped).
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = _HEADING_RE.match(stripped)
        if m:
            return stripped
        break  # Only inspect the first non-empty line
    return None


def scan_headings(pages_text: list[str]) -> list[tuple[int, str]]:
    """
    Scan a list of per-page text strings and return ``(page_index, heading)``
    tuples for every page whose first non-empty line matches a chapter heading.

    Used by the splitting ladder when no TOC is available.
    """
    results = []
    for idx, text in enumerate(pages_text):
        heading = detect_chapter(text)
        if heading is not None:
            results.append((idx, heading))
    return results
