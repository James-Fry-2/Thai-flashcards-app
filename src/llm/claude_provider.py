import anthropic
from .base import LLMProvider, LLMMessage, LLMRefusal, LLMResponse

# Models that accept server-side refusal fallbacks. The pinned SDK (0.40)
# predates these request fields, so they go through extra_headers/extra_body.
_FALLBACK_MODEL_PREFIXES = ("claude-opus-5", "claude-sonnet-5-5", "claude-fable-5")
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _response_text(response) -> str:
    """Join the text blocks; newer models also return thinking blocks first."""
    texts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
    return "".join(texts)


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, max_tokens: int = 4096, **kwargs):
        super().__init__(api_key, model, max_tokens, **kwargs)
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def complete(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        """Optional kwargs:
        json_schema -- constrain the reply to this JSON schema (structured outputs)
        effort      -- "low" | "medium" | "high" | ... (output_config.effort)
        """
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

        output_config = {}
        if kwargs.get("json_schema"):
            output_config["format"] = {"type": "json_schema", "schema": kwargs["json_schema"]}
        if kwargs.get("effort"):
            output_config["effort"] = kwargs["effort"]
        extra_body = {}
        if output_config:
            extra_body["output_config"] = output_config
        if self.model.startswith(_FALLBACK_MODEL_PREFIXES):
            extra_body["fallbacks"] = "default"
            params["extra_headers"] = {"anthropic-beta": _FALLBACK_BETA}
        if extra_body:
            params["extra_body"] = extra_body

        response = await self._client.messages.create(**params)
        if response.stop_reason == "refusal":
            raise LLMRefusal(f"{self.model} declined the request")
        return LLMResponse(
            text=_response_text(response),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
            # The pinned SDK's Usage model predates these fields but keeps extras.
            cache_creation_input_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
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
