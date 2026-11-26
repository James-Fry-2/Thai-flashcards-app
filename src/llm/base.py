from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Union


@dataclass
class LLMMessage:
    role: str  # "user" | "assistant" | "system"
    content: Union[str, list]  # list for multi-modal (vision)


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    # Prompt-cache tokens (billed at 1.25x / 0.1x input). Not every provider reports them.
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


class LLMRefusal(Exception):
    """The model declined the request (stop_reason == "refusal")."""


class LLMProvider(ABC):
    def __init__(self, api_key: str, model: str, max_tokens: int = 4096, **kwargs):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.kwargs = kwargs

    @abstractmethod
    async def complete(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        """Send a text completion request."""
        ...

    @abstractmethod
    async def complete_with_image(
        self,
        prompt: str,
        image_b64: str,
        media_type: str,
        **kwargs,
    ) -> LLMResponse:
        """Send a vision request with a base64-encoded image."""
        ...
