"""
Thai script analysis — deterministic, script-level features only.

No LLM or external network calls. All features are derived from the written
script using pythainlp + tltk (both already deps via paiboon.py).

Syllable count and tone are driven by tltk_ipa, which correctly segments
phonological syllables (dot-separated) and encodes tone as a trailing digit
(1=mid 2=low 3=falling 4=high 5=rising). This is more accurate than
counting syllable_tokenize boundaries, which occasionally under-splits
orthographic clusters (e.g. สวัสดี → 2 instead of the correct 3).

Consonant class is derived from the Thai script syllable strings produced
by syllable_tokenize (han_solo). When tltk reports more syllables than
han_solo, the extra entries fall back to "unknown" for consonant_class —
an honest limitation rather than a wrong value.

Cluster detection uses consecutive Thai consonant characters at the syllable
start. This over-fires on CVC syllables with no written vowel (e.g. สง, เทศ);
resolving that requires vowel/coda parsing which is out of scope.
"""
import sys
from typing import Any

try:
    from pythainlp.tokenize import syllable_tokenize
    from pythainlp.transliterate import transliterate
    _PYTHAINLP_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PYTHAINLP_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HIGH_CONSONANTS = set("ขฃฉฐถผฝศษสห")
MID_CONSONANTS  = set("กจฎฏดตบปอ")
LOW_CONSONANTS  = set("คฅฆงชซฌญฑฒณทธนพฟภมยรลวฬฮ")

RARE_CONSONANTS = set("ฌฎฏฐฑฒณษฬ")

TONE_MARKS: dict[str, str] = {
    "่": "low",      # ่  MAI EK
    "้": "falling",  # ้  MAI THO
    "๊": "high",     # ๊  MAI TRI
    "๋": "rising",   # ๋  MAI CHATTAWA
}

# tltk_ipa trailing digit → tone name (1=mid 2=low 3=falling 4=high 5=rising)
_TLTK_TONES: dict[str, str] = {
    "1": "mid", "2": "low", "3": "falling", "4": "high", "5": "rising",
}

GARAN = "์"  # ์  THANTHAKHAT (การันต์ — marks a silent consonant)

# Leading vowels written before the initial consonant in Thai orthography
_LEADING_VOWELS = set("เแโใไ")  # เ แ โ ใ ไ


def _is_consonant(ch: str) -> bool:
    """Return True if ch is a Thai consonant character (U+0E01–U+0E2E)."""
    return "ก" <= ch <= "ฮ"


# ---------------------------------------------------------------------------
# Per-syllable script analysis
# ---------------------------------------------------------------------------

def _analyse_syllable(syl: str, tone_override: str | None = None) -> dict[str, Any]:
    """Return a feature dict for a single Thai syllable string."""
    # --- initial consonant -------------------------------------------------
    initial = ""
    for ch in syl:
        if ch in _LEADING_VOWELS:
            continue
        if _is_consonant(ch):
            initial = ch
            break

    # --- consonant class ---------------------------------------------------
    if initial in HIGH_CONSONANTS:
        consonant_class = "high"
    elif initial in MID_CONSONANTS:
        consonant_class = "mid"
    elif initial in LOW_CONSONANTS:
        consonant_class = "low"
    else:
        consonant_class = "unknown"

    # --- tone: prefer tltk_ipa digit; fall back to explicit written mark ---
    if tone_override is not None:
        tone = tone_override
    else:
        tone = "unknown"
        for ch in syl:
            if ch in TONE_MARKS:
                tone = TONE_MARKS[ch]
                break

    # --- cluster detection: 2+ consecutive consonants at syllable start ----
    has_cluster = False
    consonant_run = 0
    past_leading = False
    for ch in syl:
        if not past_leading and ch in _LEADING_VOWELS:
            continue
        past_leading = True
        if _is_consonant(ch):
            consonant_run += 1
            if consonant_run >= 2:
                has_cluster = True
                break
        else:
            break

    return {
        "syllable": syl,
        "initial_consonant": initial,
        "consonant_class": consonant_class,
        "tone": tone,
        "has_cluster": has_cluster,
    }


def _empty_syllable(tone: str = "unknown") -> dict[str, Any]:
    """Placeholder for a syllable that exists phonologically but whose Thai
    script string was not recoverable from syllable_tokenize."""
    return {
        "syllable": "",
        "initial_consonant": "",
        "consonant_class": "unknown",
        "tone": tone,
        "has_cluster": False,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_EMPTY_RESULT: dict[str, Any] = {
    "syllable_count": 0,
    "tone_pattern": [],
    "consonant_classes": [],
    "has_cluster": False,
    "has_rare_consonant": False,
    "has_silent_mark": False,
    "script_analysis": [],
}


def analyze_thai(text: str) -> dict[str, Any]:
    """
    Return a dict of script-level features for *text*.

    Keys:
      syllable_count    int
      tone_pattern      list[str]   per syllable: low|falling|high|rising|unknown
      consonant_classes list[str]   per syllable: high|mid|low|unknown
      has_cluster       bool        any syllable starts with a 2+ consonant cluster
      has_rare_consonant bool       any of ฌ ฎ ฏ ฐ ฑ ฒ ณ ษ ฬ appears in text
      has_silent_mark   bool        การันต์ (์, U+0E4C) appears anywhere in text
      script_analysis   list[dict]  full per-syllable breakdown

    Returns empty defaults on any failure. Empty/non-Thai input also returns
    empty defaults rather than raising.
    """
    if not _PYTHAINLP_AVAILABLE:
        return dict(_EMPTY_RESULT)

    text = (text or "").strip()
    if not text:
        return dict(_EMPTY_RESULT)

    if not any("฀" <= ch <= "๿" for ch in text):
        return dict(_EMPTY_RESULT)

    # --- tltk_ipa: authoritative syllable count + tone ---------------------
    # tltk uses "." as syllable separator and a trailing digit (1-5) for tone.
    tltk_tones: list[str] = []
    syllable_count = 0
    try:
        ipa = transliterate(text, engine="tltk_ipa")
        if ipa:
            ipa_parts = ipa.split(".")
            syllable_count = len(ipa_parts)
            tltk_tones = [
                _TLTK_TONES.get(p[-1], "unknown") if p and p[-1].isdigit() else "unknown"
                for p in ipa_parts
            ]
    except Exception:
        pass

    # --- han_solo: Thai script syllable strings for consonant class --------
    try:
        thai_syls = syllable_tokenize(text)
    except Exception:
        thai_syls = []

    # Fall back to han_solo count if tltk produced nothing
    if not syllable_count:
        syllable_count = len(thai_syls)
        tltk_tones = ["unknown"] * syllable_count

    if not syllable_count:
        return dict(_EMPTY_RESULT)

    try:
        per_syllable: list[dict[str, Any]] = []
        for i in range(syllable_count):
            tone = tltk_tones[i] if i < len(tltk_tones) else "unknown"
            if i < len(thai_syls):
                entry = _analyse_syllable(thai_syls[i], tone_override=tone)
            else:
                # tltk found a syllable that han_solo merged with a neighbour
                entry = _empty_syllable(tone)
            per_syllable.append(entry)

        return {
            "syllable_count":    syllable_count,
            "tone_pattern":      [s["tone"]            for s in per_syllable],
            "consonant_classes": [s["consonant_class"] for s in per_syllable],
            "has_cluster":       any(s["has_cluster"]  for s in per_syllable),
            "has_rare_consonant": any(ch in RARE_CONSONANTS for ch in text),
            "has_silent_mark":   GARAN in text,
            "script_analysis":   per_syllable,
        }
    except Exception:
        return dict(_EMPTY_RESULT)


# ---------------------------------------------------------------------------
# CLI helper  (python -m src.utils.thai_analysis <word1> <word2> ...)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json

    words = sys.argv[1:] if len(sys.argv) > 1 else [
        "สวัสดี",        # hello — 3 syllables (sa-wat-di)
        "กินข้าว",       # eat rice — tone mark, no cluster
        "ประเทศไทย",     # Thailand — clusters
        "รถยนต์",        # car — silent mark (การันต์)
        "กระทะ",         # wok — cluster กร
        "เดิน",          # walk — leading vowel เ
        "ฉลาด",          # smart — high-class initial
        "สงสัย",         # doubt
        "ฌาน",           # dhyana — rare consonant ฌ
        "กษัตริย์",      # king — rare consonant ษ + silent mark
    ]
    for w in words:
        result = analyze_thai(w)
        summary = {k: v for k, v in result.items() if k != "script_analysis"}
        print(f"{w}")
        print(f"  {json.dumps(summary, ensure_ascii=False)}")
        for syl in result["script_analysis"]:
            print(f"    {json.dumps(syl, ensure_ascii=False)}")
        print()
