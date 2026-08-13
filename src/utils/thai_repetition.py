"""
Thai reduplication mark handling — ๆ (U+0E46, "mai yamok").

Written Thai omits the repeated word: ๆ marks that the preceding word (or,
less commonly, phrase) is pronounced twice — เด็กๆ "dek dek" (children/kids,
plural-ish), เรื่อยๆ "rueai rueai" (continuously). None of the underlying
romanization engines (tltk_ipa, PyThaiNLP's royin) expand this on their own,
so every romanization scheme needs the same fix: expand ๆ to a literal
duplicate of the word it marks *before* handing text to the
tokenizer/converter. PyThaiNLP's newmm tokenizer is inconsistent about
whether ๆ ends up attached to the preceding token (เรื่อยๆ) or split into its
own token (เด็ก, ๆ) — this handles both.
"""
MAI_YAMOK = "ๆ"  # ๆ

try:
    from pythainlp.tokenize import word_tokenize
    _AVAILABLE = True
except ImportError:  # pragma: no cover
    _AVAILABLE = False


def expand_repetition_marks(text: str) -> str:
    """
    Replace every ๆ with a literal repeat of the word it marks.

      เด็กๆ   -> "เด็ก เด็ก"   (mark attached directly to the word)
      เด็ก ๆ  -> "เด็ก เด็ก"   (mark tokenized separately)

    Returns *text* unchanged if it contains no ๆ, or if PyThaiNLP is
    unavailable (callers already no-op in that case).
    """
    if MAI_YAMOK not in text or not _AVAILABLE:
        return text

    try:
        tokens = word_tokenize(text, engine="newmm")
    except Exception:
        return text

    expanded: list[str] = []
    for raw_token in tokens:
        token = raw_token.strip()
        if not token:
            continue
        if token == MAI_YAMOK:
            if expanded:
                expanded.append(expanded[-1])
            # else: leading ๆ with nothing to repeat — drop it
        elif token.endswith(MAI_YAMOK) and len(token) > 1:
            base = token[:-1]
            expanded.append(base)
            expanded.append(base)
        else:
            expanded.append(token)

    return " ".join(expanded)
