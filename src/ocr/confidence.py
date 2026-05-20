from dataclasses import dataclass
from typing import Optional


@dataclass
class OcrResult:
    text: str
    engine_used: str  # "paddle" | "easy" | "claude_vision"
    confidence: float  # 0.0–1.0; Claude Vision always returns 1.0
