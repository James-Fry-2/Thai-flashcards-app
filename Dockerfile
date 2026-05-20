# ---- Stage 1: Build React frontend ----
FROM node:20-alpine AS frontend-build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build
# Output goes to /app/dist (vite.config.ts sets outDir: '../static'
# but that resolves to /app/static inside this stage)

# ---- Stage 2: Python app ----
FROM python:3.12-slim AS app

# System deps for pdf2image (poppler) and OpenCV/PaddleOCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpoppler-cpp-dev \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Copy built frontend from stage 1
# vite outDir is '../static' relative to frontend/, so the built files land at /app/dist
COPY --from=frontend-build /app/dist ./static

# Default data dir (overridden by docker volume mount)
RUN mkdir -p /data/media/uploads

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn src.main:app --host 0.0.0.0 --port 8000"]
