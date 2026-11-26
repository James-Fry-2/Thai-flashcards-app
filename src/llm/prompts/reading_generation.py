"""Prompts for generated reading practice: write a dialogue or example
sentences around a learner's vocabulary, simplify it if it came out too
hard, then check it in a second pass."""
import json

GENERATION_SYSTEM = """You write short Thai reading practice for an adult English speaker who is a beginner: they can read only a few hundred Thai words. The learner reads your text in an app that highlights which words they already know, so every word outside their vocabulary is visibly hard for them.

What makes the text useful:
- It reads like something real people would say. Start from ONE ordinary, believable situation (ordering at a food stall, asking a neighbour about their weekend, buying a train ticket) and let every line follow naturally from the line before. No sudden topic changes, no odd or comic plot turns, nothing that only exists to fit a word in.
- It is easy: CEFR A1 level. Lines of about 3 to 8 words, the simplest common grammar, one idea per line. Use the learner's KNOWN words and the most common everyday Thai words; avoid anything rarer. If a word isn't needed, leave it out.
- It is natural spoken Bangkok Thai, not textbook-stiff or translated from English. Use polite particles the way real speakers do, matched to the speaker's gender (ครับ for a man, ค่ะ/คะ for a woman), and not on every line.
- The English is a natural translation of what each line means, not a word-by-word gloss.
- Thai is written in Thai script only, with no romanization.

Return only the JSON the schema asks for."""

DIALOGUE_INSTRUCTIONS = """From the CANDIDATE words, choose the {n_min} to {n_max} that fit together most naturally in one simple everyday scene that suits the topic, and write a dialogue of 6 to 8 short lines in that scene. Don't use the other candidates: a natural scene matters more than covering words.
Use two speakers with common Thai first names (e.g. สมชาย, นิด, ต้น, แพร), keeping each speaker's gender consistent with their particles.
Put the speaker's name in "speaker" and leave "word" empty on every line.
Give it a short English title describing the scene."""

SENTENCES_INSTRUCTIONS = """From the CANDIDATE words, choose the {n_min} to {n_max} most useful everyday ones, and write 2 short, simple example sentences for each, showing how it is commonly used. The two sentences for a word should use different patterns (e.g. a statement and a question).
Put the chosen word (exactly as given) in "word" and leave "speaker" empty. Keep each word's sentences together.
Give it a short English title."""

TEXT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string"},
                    "word": {"type": "string"},
                    "thai": {"type": "string"},
                    "english": {"type": "string"},
                },
                "required": ["speaker", "word", "thai", "english"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "lines"],
    "additionalProperties": False,
}

TARGET_RANGE = {"dialogue": (3, 4), "sentences": (3, 4)}


def generation_prompt(
    kind: str,
    topic: str,
    candidates: list[dict],
    known: list[str],
    vocab_size: int,
) -> str:
    cand_block = "\n".join(f"- {c['thai']} ({c['english']})" for c in candidates)
    known_block = " ".join(known) if known else "(none yet)"
    n_min, n_max = TARGET_RANGE[kind]
    template = DIALOGUE_INSTRUCTIONS if kind == "dialogue" else SENTENCES_INSTRUCTIONS
    return f"""Topic: {topic}
The learner knows roughly {vocab_size} Thai words.

CANDIDATE words to practise (the first ones are the words they are learning right now):
{cand_block}

KNOWN words the learner can already read (reuse these freely):
{known_block}

{template.format(n_min=n_min, n_max=n_max)}"""


def simplify_prompt(kind: str, title: str, lines: list[dict], hard_words: list[str]) -> str:
    what = "dialogue" if kind == "dialogue" else "set of example sentences"
    payload = {"title": title, "lines": lines}
    return f"""This {what} is too hard for the learner. These words are outside their vocabulary and not common enough: {" ".join(hard_words)}

Rewrite it so it keeps the same scene and the same practice words, but replace or drop those hard words with simpler, more common ones, and keep every line short. Keep the same JSON shape.

{json.dumps(payload, ensure_ascii=False, indent=1)}"""


CHECK_SYSTEM = """You are a native Thai speaker and experienced teacher of Thai to beginners, reviewing short reading practice another writer produced for an English-speaking learner. The learner will trust this text, so anything unnatural teaches them something wrong.

First judge the text as a whole:
- Would two real Thai people actually have this exchange (or would a teacher really give these example sentences)? Does each line follow sensibly from the one before, with no strange jumps or contrived plot?
- Is it simple enough for a beginner?
If it fails either test, set overall.natural to false, explain the problem in one sentence, and put a complete rewritten version in "rewrite": same practice words, same JSON line shape (speaker, word, thai, english), simpler and natural. Otherwise set overall.natural to true and leave "rewrite" empty.

Then, for each original line, decide whether it is natural, whether the polite particles match the speaker's gender, whether a given target word is used correctly, and whether the English accurately conveys the Thai. Return verdict "ok" (thai and english unchanged, empty note) or "fixed" (corrected thai and/or english, kept simple, plus a one-sentence note on what you changed and why). Don't rewrite lines just for style.

Return only the JSON the schema asks for."""

_LINE = {
    "type": "object",
    "properties": {
        "speaker": {"type": "string"},
        "word": {"type": "string"},
        "thai": {"type": "string"},
        "english": {"type": "string"},
    },
    "required": ["speaker", "word", "thai", "english"],
    "additionalProperties": False,
}

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "overall": {
            "type": "object",
            "properties": {
                "natural": {"type": "boolean"},
                "problem": {"type": "string"},
            },
            "required": ["natural", "problem"],
            "additionalProperties": False,
        },
        "rewrite": {"type": "array", "items": _LINE},
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "verdict": {"type": "string", "enum": ["ok", "fixed"]},
                    "thai": {"type": "string"},
                    "english": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["index", "verdict", "thai", "english", "note"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overall", "rewrite", "lines"],
    "additionalProperties": False,
}


def check_prompt(kind: str, lines: list[dict]) -> str:
    payload = [
        {"index": i, "speaker": l["speaker"], "target_word": l["word"], "thai": l["thai"], "english": l["english"]}
        for i, l in enumerate(lines)
    ]
    what = "dialogue" if kind == "dialogue" else "set of example sentences"
    return f"Review this {what}:\n\n{json.dumps(payload, ensure_ascii=False, indent=1)}"
