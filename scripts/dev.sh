#!/bin/bash
# Quick dev startup: run FastAPI on :8000 and Vite dev server on :5173
# Requires: Python venv at .venv, Node/npm in PATH

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Starting FastAPI dev server..."
cd "$ROOT"
mkdir -p data/media/uploads
DATABASE_URL="sqlite+aiosqlite:///./data/dek_kard.db" \
MEDIA_DIR="./data/media" \
  .venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload &
API_PID=$!

echo "Starting Vite dev server..."
cd "$ROOT/frontend"
npm run dev &
VITE_PID=$!

trap "kill $API_PID $VITE_PID 2>/dev/null; exit 0" INT TERM

echo ""
echo "  API:      http://localhost:8000"
echo "  Docs:     http://localhost:8000/docs"
echo "  Frontend: http://localhost:5173"
echo ""
echo "Press Ctrl+C to stop"
wait
