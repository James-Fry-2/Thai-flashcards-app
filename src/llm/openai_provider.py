"""
OpenAI provider — ready but not wired by default.
Set CARD_GENERATION_PROVIDER=openai in .env to use.
"""
import base64
import openai
from .base import LLMProvider, LLMMessage, LLMResponse


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, max_tokens: int = 4096, **kwargs):
        super().__init__(api_key, model, max_tokens, **kwargs)
        self._client = openai.AsyncOpenAI(api_key=api_key)

    async def complete(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        response = await self._client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": m.role, "content": m.content} for m in messages],
        )
        choice = response.choices[0]
        return LLMResponse(
            text=choice.message.content or "",
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            model=response.model,
        )

    async def complete_with_image(
        self,
        prompt: str,
        image_b64: str,
        media_type: str,
        **kwargs,
    ) -> LLMResponse:
        response = await self._client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{media_type};base64,{image_b64}"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        choice = response.choices[0]
        return LLMResponse(
            text=choice.message.content or "",
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            model=response.model,
        )
