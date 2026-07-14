from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from loguru import logger

from src.config.settings import get_settings
from src.db.database import get_engine, get_session_factory
from src.db.models import Base
from src.db.services.gamification_service import seed_achievements
from src.llm.registry import register_providers
from src.api.routes import uploads, decks, cards, review, export, gamification, analytics, tags, links, topics, search


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Starting dek-kard...")

    # Ensure data directories exist
    Path(settings.media_dir).mkdir(parents=True, exist_ok=True)
    (Path(settings.media_dir) / "uploads").mkdir(exist_ok=True)

    # Create tables (Alembic handles migrations; this is a safety net for dev)
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed achievements
    factory = get_session_factory()
    async with factory() as db:
        await seed_achievements(db)
        await db.commit()

    # Register LLM providers
    register_providers(settings)
    logger.info("LLM providers registered")

    yield

    await get_engine().dispose()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Dek-Kard",
        description="Thai language flashcard app",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Tighten in production if needed
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes
    prefix = "/api"
    app.include_router(uploads.router, prefix=prefix)
    app.include_router(decks.router, prefix=prefix)
    app.include_router(cards.router, prefix=prefix)
    app.include_router(review.router, prefix=prefix)
    app.include_router(export.router, prefix=prefix)
    app.include_router(gamification.router, prefix=prefix)
    app.include_router(analytics.router, prefix=prefix)
    app.include_router(tags.router, prefix=prefix)
    app.include_router(links.router, prefix=prefix)
    app.include_router(topics.router, prefix=prefix)
    app.include_router(search.router, prefix=prefix)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # Serve React frontend (built into ./static in Docker; skip in dev)
    # A catch-all route is used instead of StaticFiles mount so that SPA routes
    # like /dashboard are served index.html rather than a 404.
    static_dir = Path("static")
    if static_dir.exists():
        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            file_path = static_dir / full_path
            if file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
