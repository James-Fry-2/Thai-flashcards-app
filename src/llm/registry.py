from enum import Enum
from typing import Dict
from .base import LLMProvider


class LLMTask(str, Enum):
    OCR_FALLBACK = "ocr_fallback"
    CARD_GENERATION = "card_generation"
    IMAGE_GENERATION = "image_generation"  # future
    LINK_SUGGESTION = "link_suggestion"


_registry: Dict[LLMTask, LLMProvider] = {}


def register_providers(settings) -> None:
    """Called once at app startup to configure per-task providers."""
    from .claude_provider import ClaudeProvider
    from .openai_provider import OpenAIProvider

    provider_classes = {
        "claude": ClaudeProvider,
        "openai": OpenAIProvider,
    }

    task_configs = {
        LLMTask.OCR_FALLBACK: {
            "provider": settings.ocr_fallback_provider,
            "model": settings.ocr_fallback_model,
            "max_tokens": 2048,
        },
        LLMTask.CARD_GENERATION: {
            "provider": settings.card_generation_provider,
            "model": settings.card_generation_model,
            "max_tokens": 16384,
        },
        LLMTask.LINK_SUGGESTION: {
            "provider": settings.card_generation_provider,
            "model": settings.card_generation_model,
            "max_tokens": 1024,
        },
    }

    for task, cfg in task_configs.items():
        provider_name = cfg["provider"]
        cls = provider_classes.get(provider_name)
        if not cls:
            raise ValueError(f"Unknown LLM provider: {provider_name}")

        api_key = (
            settings.anthropic_api_key
            if provider_name == "claude"
            else settings.openai_api_key
        )
        _registry[task] = cls(
            api_key=api_key,
            model=cfg["model"],
            max_tokens=cfg["max_tokens"],
        )


def get_provider(task: LLMTask) -> LLMProvider:
    provider = _registry.get(task)
    if not provider:
        raise RuntimeError(f"No provider registered for task: {task}. Did you call register_providers()?")
    return provider
