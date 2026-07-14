from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "sqlite+aiosqlite:////data/dek_kard.db"

    # Media
    media_dir: str = "/data/media"

    # LLM providers
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Per-task LLM config
    ocr_fallback_provider: str = "claude"
    ocr_fallback_model: str = "claude-3-5-haiku-20241022"
    card_generation_provider: str = "claude"
    card_generation_model: str = "claude-opus-4-6"
    card_tagging_provider: str = "claude"
    card_tagging_model: str = "claude-haiku-4-5-20251001"

    # Embeddings
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    # OCR
    ocr_confidence_threshold: float = 0.60
    ironocr_url: str = ""  # e.g. http://ironocr:5050 — leave empty to skip

    # Uploads
    max_upload_size_mb: int = 20

    # App
    secret_key: str = "change-me"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
