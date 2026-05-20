import anthropic
from .base import LLMProvider, LLMMessage, LLMResponse


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, max_tokens: int = 4096, **kwargs):
        super().__init__(api_key, model, max_tokens, **kwargs)
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def complete(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        # Separate system message if present
        system = None
        filtered = []
        for m in messages:
            if m.role == "system":
                system = m.content
            else:
                filtered.append({"role": m.role, "content": m.content})

        params = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": filtered,
        }
        if system:
            # Pass as a content block so cache_control can be attached.
            # Anthropic caches this for 5 min — saves ~75% on system prompt tokens
            # for repeated calls (e.g. multiple uploads in a session).
            params["system"] = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        response = await self._client.messages.create(**params)
        return LLMResponse(
            text=response.content[0].text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
        )

    async def complete_with_image(
        self,
        prompt: str,
        image_b64: str,
        media_type: str,
        **kwargs,
    ) -> LLMResponse:
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        return LLMResponse(
            text=response.content[0].text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
        )
