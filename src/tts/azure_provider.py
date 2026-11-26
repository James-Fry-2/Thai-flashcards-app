"""Azure AI Speech (Neural voices) over the REST API — no SDK needed.

https://learn.microsoft.com/azure/ai-services/speech-service/rest-text-to-speech
"""
from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

import httpx

from .base import TTSError

OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"


def build_ssml(text: str, voice: str, rate: str) -> str:
    body = escape(text)
    if rate and rate not in ("0%", "+0%", "default"):
        body = f"<prosody rate={quoteattr(rate)}>{body}</prosody>"
    return (
        "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='th-TH'>"
        f"<voice name={quoteattr(voice)}>{body}</voice></speak>"
    )


class AzureTTSProvider:
    name = "azure"

    def __init__(self, api_key: str, region: str, timeout: float = 20.0):
        self.api_key = api_key
        self.region = region
        self.timeout = timeout

    @property
    def endpoint(self) -> str:
        return f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1"

    async def synthesize(self, text: str, voice: str, rate: str) -> bytes:
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": OUTPUT_FORMAT,
            "User-Agent": "dek-kard",
        }
        ssml = build_ssml(text, voice, rate).encode("utf-8")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.endpoint, headers=headers, content=ssml)
        except httpx.HTTPError as exc:
            raise TTSError(f"Azure TTS request failed: {exc}") from exc
        if resp.status_code != 200:
            raise TTSError(f"Azure TTS returned {resp.status_code}: {resp.text[:200]}")
        if not resp.content:
            raise TTSError("Azure TTS returned no audio")
        return resp.content
