"""Text-to-speech provider interface.

A provider turns one short piece of Thai text into MP3 bytes. Caching,
validation and usage accounting live in src/db/services/tts_service.py, so
providers stay thin HTTP wrappers.
"""
from __future__ import annotations

from typing import Protocol


class TTSError(RuntimeError):
    """The provider failed (network, auth, quota, bad response)."""


class TTSNotConfigured(TTSError):
    """No provider is configured (e.g. missing API key)."""


class TTSProvider(Protocol):
    name: str

    async def synthesize(self, text: str, voice: str, rate: str) -> bytes:
        """Return MP3 audio for *text*. ``rate`` is an SSML prosody rate
        such as ``"0%"`` or ``"-30%"``."""
        ...
