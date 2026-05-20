# Dek-Kard

Self-hosted Thai language flashcard app. Upload PDFs or photos of your notes, auto-generate cards via Claude, review with spaced repetition (FSRS), and export to Anki.

## Features

- **OCR pipeline** — PaddleOCR → EasyOCR → Claude Vision (confidence-based fallback)
- **AI card generation** — Claude extracts Thai vocabulary with romanization, English translation, and example sentences
- **Spaced repetition** — FSRS algorithm with per-direction schedules (Thai→English, English→Thai, listening)
- **Gamification** — XP, levels, streaks, and achievements
- **Anki export** — Download any deck as `.apkg`
- **Single container** — SQLite + React frontend, no external services required

---

## Quick Start (Docker)

**1. Clone and configure**

```bash
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY
```

**2. Run**

```bash
docker compose up --build
```

App is available at [http://localhost:8000](http://localhost:8000).

**Backup your data:**

```bash
cp -r ./data ./backup-$(date +%Y%m%d)
```

---

## Local Development

**Requirements:** Python 3.12+, Node 20+

**Backend**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run migrations
alembic upgrade head

# Start API (with hot reload)
DATABASE_URL="sqlite+aiosqlite:///./data/dek_kard.db" \
MEDIA_DIR="./data/media" \
ANTHROPIC_API_KEY="sk-ant-..." \
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

**Or use the dev script (runs both together):**

```bash
# Requires .venv to be set up and ANTHROPIC_API_KEY in environment
bash scripts/dev.sh
```

| Service | URL |
|---|---|
| Frontend (Vite dev) | http://localhost:5173 |
| API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |

---

## Environment Variables

Copy `.env.example` to `.env` and edit:

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(required)* | Anthropic API key |
| `OPENAI_API_KEY` | *(optional)* | Only needed if switching a task to OpenAI |
| `DATABASE_URL` | `sqlite+aiosqlite:////data/dek_kard.db` | SQLite path (in Docker: `/data/`) |
| `MEDIA_DIR` | `/data/media` | Uploaded file storage |
| `CARD_GENERATION_MODEL` | `claude-opus-4-6` | Model used to generate flashcards |
| `OCR_FALLBACK_MODEL` | `claude-3-5-haiku-20241022` | Model used when local OCR confidence is low |
| `OCR_CONFIDENCE_THRESHOLD` | `0.75` | Below this, OCR falls back to next engine |
| `MAX_UPLOAD_SIZE_MB` | `20` | Maximum upload file size |
| `SECRET_KEY` | *(required)* | App secret — set to any 32+ char string |

---

## Usage

### Uploading documents

1. Navigate to **Upload** in the app
2. Drop a PDF or image (Thai text, notes, screenshots, etc.)
3. The app will OCR the file, extract vocabulary, and generate flashcards
4. Poll the upload status — cards appear in the deck when `status: done`

Supported formats: PDF, PNG, JPG, JPEG, WEBP

### Reviewing cards

1. Open a deck → **Start Review**
2. Rate each card: **Again (1)** / **Hard (2)** / **Good (3)** / **Easy (4)**
3. FSRS schedules the next review automatically
4. XP and streak update after each session

### Exporting to Anki

From any deck's detail page, click **Export to Anki** to download an `.apkg` file importable into [Anki](https://apps.ankiweb.net).

---

## API Reference

The full interactive API docs are at `/docs` when the server is running.

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/uploads/` | Upload file → background OCR + card generation |
| `GET` | `/api/uploads/{id}` | Poll upload job status |
| `GET` | `/api/decks/` | List decks |
| `POST` | `/api/decks/` | Create a deck |
| `GET` | `/api/decks/{id}/cards` | Paginated card list |
| `POST` | `/api/cards/{id}` | Create card manually |
| `PATCH` | `/api/cards/{id}` | Edit card |
| `DELETE` | `/api/cards/{id}` | Delete card |
| `POST` | `/api/review/session` | Start SRS session |
| `POST` | `/api/review/session/{id}/rate` | Submit rating (1–4) |
| `POST` | `/api/review/session/{id}/end` | End session |
| `GET` | `/api/export/decks/{id}/anki` | Download `.apkg` |
| `GET` | `/api/gamification/profile` | XP, level, streak, achievements |
| `GET` | `/health` | Health check |

---

## Project Structure

```
dek-kard/
├── src/                    # Python backend (FastAPI)
│   ├── main.py             # App entry point
│   ├── config/             # Settings (pydantic-settings)
│   ├── db/
│   │   ├── models/         # SQLAlchemy ORM models
│   │   └── services/       # Business logic
│   ├── llm/                # LLM provider abstraction (Claude, OpenAI)
│   │   └── prompts/        # Card generation + OCR fallback prompts
│   ├── ocr/                # OCR pipeline (PaddleOCR → EasyOCR → Claude Vision)
│   ├── tasks/              # Background upload processing
│   ├── api/routes/         # REST endpoints
│   └── utils/              # FSRS scheduler, Anki exporter, file parser
├── frontend/               # React 18 + TypeScript + TailwindCSS
│   └── src/
│       ├── pages/          # Upload, Decks, DeckDetail, Review, Dashboard
│       └── components/     # FlashCard, XPBar, StreakBadge, UploadDropzone
├── alembic/                # Database migrations
├── scripts/dev.sh          # Local dev startup script
├── docker-compose.yml
├── Dockerfile
└── .env.example
```

---

## Database

SQLite by default, stored at `./data/dek_kard.db`. The schema is SQLAlchemy-managed and PostgreSQL-compatible if you ever need to scale.

**Reset SRS state for a deck** (cards reappear as new):

```sql
DELETE FROM card_schedules
WHERE card_id IN (SELECT id FROM cards WHERE deck_id = <deck_id>);
```

**Migrations:**

```bash
# Apply all pending migrations
alembic upgrade head

# Create a new migration after model changes
alembic revision --autogenerate -m "description"
```
