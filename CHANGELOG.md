# Changelog

All notable changes to Baimai (formerly Dek-Kard) are listed here. Versions follow [Semantic Versioning](https://semver.org).

## [Unreleased]

### Brand
- The app is now called **Baimai** (ใบไม้, "leaf"). The brand system, tokens, logo and decision log are in `brand/`.
- New look: a bright leaf-green palette on a ruled-paper background, rounded Mitr headings, chunky buttons, and Bai the leaf in the nav bar.
- Text contrast now meets WCAG 2.2 AA throughout. About 430 too-light text colours were darkened, and form-control borders now reach 3:1.
- Review and practice grade buttons: only "Good" is filled, and "Again" is marked with a cross as well as colour.
- New setting: **Thai card font**. Choose Learner (looped, the default), Classic, Real-world (loopless) or Handwriting.

## [1.0.0] — 2026-11-22

First public release. A self-hosted app that turns Thai study material into reviewed, spaced-repetition flashcards.

### Card creation
- Upload PDFs, whole textbooks or photos of notes. Text goes through a layered OCR pipeline (embedded PDF text, then PaddleOCR, then EasyOCR, then Claude Vision), and each stage hands off to the next when its confidence is too low.
- Claude extracts vocabulary and generates cards with English translation, example sentences and topic tags.
- Book import detects chapter boundaries from font, layout, lexical and topic-shift signals. You confirm the splits in a split-review screen with page thumbnails.
- A resilient background upload worker checkpoints each stage, recovers after restarts and shows live progress.
- Duplicate detection and a text-integrity guard reject corrupted OCR output (U+FFFD, private-use and control characters).

### Learning
- FSRS spaced repetition with separate schedules for each direction (Thai→English, English→Thai, listening).
- Practice mode mixes multiple-choice and recall exercises, with distractors picked to be plausible.
- Review queues for each deck, topic, book chapter, search result and "at risk" set of cards.
- Learner insights: mastery bands, roll-ups by topic, chapter and card type, error patterns and progress trends.
- XP, levels, streaks and achievements.

### Thai language tooling
- Romanization in several schemes (RTGS, Paiboon, IPA). The scheme you choose applies across the app.
- Compound-word breakdown: dictionary segmentation into morphemes with glosses from the Volubilis lexicon, plus English word-frequency ranking to pick the right sense.
- Detection of confusable pairs that sound alike (IPA edit distance) or look alike (Thai-script edit distance), linked between cards.
- Semantic search over cards using multilingual sentence embeddings.

### Quality control
- Possible mistranslations are flagged automatically, and an LLM can verify them on request.
- A triage screen works through flagged cards. Your corrections are stored as overrides on top of the generated card, so the original is kept.
- Anki export (`.apkg`) for any deck.

### Engineering
- FastAPI and async SQLAlchemy on SQLite, with 24 Alembic migrations. React 18, TypeScript and Tailwind frontend.
- An LLM provider abstraction lets you choose the model for each task (Claude by default, OpenAI optional).
- 312 backend tests. GitHub Actions runs CI, and pushing a release tag publishes the Docker image to GHCR.
- The app ships as a single container. The IronOCR sidecar is now optional through a Compose profile.
