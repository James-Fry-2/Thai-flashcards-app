"""Thai script → RTGS (Royal Thai General System) romanization.

Uses PyThaiNLP romanize with the 'royin' engine (ASCII, no tone marks).
Returns an empty string on any failure so callers never crash.
"""
try:
    from pythainlp.transliterate import romanize as _romanize
    _AVAILABLE = True
except ImportError:  # pragma: no cover
    _AVAILABLE = False


def thai_to_rtgs(text: str) -> str:
    """Convert Thai script to RTGS romanization.

    Returns an empty string when PyThaiNLP is unavailable or conversion fails.
    """
    if not _AVAILABLE:
        return ""
    text = text.strip()
    if not text:
        return ""
    try:
        result = _romanize(text, engine="royin")
        return result or ""
    except Exception:
        return ""
