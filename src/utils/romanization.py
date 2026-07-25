"""Romanization dispatcher: generate all schemes + resolve the effective value."""
from typing import Optional

SCHEMES = ("paiboon", "rtgs", "ipa")


def generate_all(thai: str) -> dict:
    """Return {paiboon, rtgs, ipa} for *thai*. Empty strings on failure, never raises."""
    from src.utils.paiboon import thai_to_paiboon
    from src.utils.rtgs import thai_to_rtgs
    from src.utils.ipa_romanization import thai_to_ipa
    return {
        "paiboon": thai_to_paiboon(thai),
        "rtgs": thai_to_rtgs(thai),
        "ipa": thai_to_ipa(thai),
    }


def resolve_effective(values: dict, prefs) -> Optional[str]:
    """Resolve the single display romanization from all stored columns + preferences.

    Precedence:
      1. romanization_manual  (always wins)
      2. romanization_{display}  if non-empty
      3. romanization_{fallback}  if non-empty and fallback != 'none'
    """
    manual = values.get("romanization_manual") or None
    if manual:
        return manual

    display = getattr(prefs, "romanization_display", "source")
    display_val = values.get(f"romanization_{display}") or None
    if display_val:
        return display_val

    fallback = getattr(prefs, "romanization_fallback", "paiboon")
    if fallback != "none":
        fallback_val = values.get(f"romanization_{fallback}") or None
        if fallback_val:
            return fallback_val

    return None
