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
    max_book_upload_size_mb: int = 300

    # PDF text extraction (§6): pages with >= this many chars skip rasterize + OCR
    pdf_text_min_chars: int = 40

    # Card generation chunking (§7): text exceeding this triggers per-chunk generation
    card_generation_char_budget: int = 12000

    # Chapter detection — Tier 1 thresholds
    chapter_font_size_ratio: float = 1.8       # span size ≥ ratio × modal body size → font_outlier
    chapter_sparse_percentile: int = 10        # char count below Nth percentile → sparse_page
    chapter_boundary_threshold: float = 0.45  # weighted score above this → boundary candidate
    chapter_topic_shift_enabled: bool = True   # enable embedding-based topic-shift signal
    chapter_topic_shift_threshold: float = 0.50  # cosine similarity below this → topic_shift
    chapter_example_match_threshold: float = 0.75  # teach-by-example score above this → proposed match

    # Chapter detection — signal weights (must sum to something sensible; see chapter_signals.py)
    chapter_weight_font_outlier: float = 0.35
    chapter_weight_sparse_page: float = 0.25
    chapter_weight_template_match: float = 0.30
    chapter_weight_header_change: float = 0.20
    chapter_weight_recto_start: float = 0.05
    chapter_weight_lexical_hit: float = 0.40
    chapter_weight_topic_shift: float = 0.20

    # Thumbnail rendering
    chapter_thumbnail_dpi: int = 50  # low-res thumbnail DPI for the review filmstrip

    # Compound breakdown
    compound_gloss_llm_fallback: bool = False  # default off — keeps bulk ingestion free
    compound_max_syllables: int = 3            # inputs with more syllables are skipped

    # App
    secret_key: str = "change-me"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
