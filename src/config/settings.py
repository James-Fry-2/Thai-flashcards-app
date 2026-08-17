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

    # Compound breakdown — surface guard
    compound_surface_min_gloss_ratio: float = 1.0  # fraction of parts that must resolve a gloss to surface (1.0 = all)

    # Confusable detection (deterministic phonetic/orthographic pass)
    confusable_max_phonetic: float = 0.34     # normalized IPA edit distance — ~1 edit in a 3-phone word
    confusable_max_orthographic: int = 1      # Thai-script edit distance — differ by a single character/mark
    confusable_min_length: int = 2            # skip words shorter than this (1-char words generate noise)

    # Mastery classification (learner feedback / analytics)
    mastery_min_reviews: int = 3                     # below this a card is "still_learning"
    mastery_again_rate_struggling: float = 0.30      # recency-weighted again-rate at/above this -> struggling
    mastery_group_min_cards: int = 5                 # a group needs this many reviewed cards to be ranked
    mastery_recency_half_life_days: float = 30.0     # exponential decay half-life for recency-weighted again-rate
    mastery_lapses_struggling: int = 4               # fsrs_lapses at/above this -> struggling
    mastery_retrievability_struggling: float = 0.70  # relearning + retrievability below this -> struggling
    mastery_retrievability_solid: float = 0.85       # retrievability at/above this counts toward "solid"
    mastery_stability_fragile_days: float = 21.0     # fsrs_stability below this (days) -> fragile (if not struggling)
    mastery_accuracy_solid_max_again_rate: float = 0.10  # again-rate at/below this counts toward "solid"

    # Pattern detection (baseline-compared insights)
    pattern_min_reviewed_cards: int = 8   # a subgroup needs at least this many reviewed cards to report a pattern
    pattern_effect_size: float = 0.15     # minimum absolute again-rate gap vs baseline to surface a pattern

    # Multiple-choice quiz distractor selection — semantic near-neighbour band.
    # Below min: unrelated (useless distractor). Above max: near-synonym (broken item).
    distractor_semantic_min: float = 0.45
    distractor_semantic_max: float = 0.75

    # App
    secret_key: str = "change-me"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
