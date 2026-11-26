"""Text-to-speech providers. ``get_tts_provider()`` returns the configured
provider or raises TTSNotConfigured; tests monkeypatch it."""
from __future__ import annotations

from src.config.settings import get_settings

from .base import TTSError, TTSNotConfigured, TTSProvider

__all__ = ["TTSError", "TTSNotConfigured", "TTSProvider", "get_tts_provider", "is_configured"]


def is_configured(settings=None) -> bool:
    settings = settings or get_settings()
    return settings.tts_provider == "azure" and bool(settings.azure_speech_key)


def get_tts_provider(settings=None) -> TTSProvider:
    settings = settings or get_settings()
    if settings.tts_provider != "azure":
        raise TTSNotConfigured(f"Unknown TTS provider: {settings.tts_provider!r}")
    if not settings.azure_speech_key:
        raise TTSNotConfigured("AZURE_SPEECH_KEY is not set")
    from .azure_provider import AzureTTSProvider

    return AzureTTSProvider(settings.azure_speech_key, settings.azure_speech_region)
