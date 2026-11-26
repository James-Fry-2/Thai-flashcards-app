"""Claude API prices and cost estimates.

Prices are USD per million tokens, Anthropic first-party API rates as of
2026-11 (check https://www.anthropic.com/pricing when they change). Cache
writes are billed at 1.25x the input price and cache reads at 0.1x.

``estimate`` re-prices token counts that one model actually used at another
model's rates. Treat it as a rough guide: other models think for different
lengths and some tokenize text differently, so their real token counts
won't be identical.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Price:
    label: str
    input: float   # $ per 1M input tokens
    output: float  # $ per 1M output tokens


PRICES: dict[str, Price] = {
    "claude-fable-5-2": Price("Claude Fable 5.2", 8.00, 40.00),
    "claude-opus-5-5": Price("Claude Opus 5.5", 4.00, 20.00),
    "claude-sonnet-5-5": Price("Claude Sonnet 5.5", 2.00, 10.00),
    "claude-haiku-5-5": Price("Claude Haiku 5.5", 0.10, 0.50),
    # Older models still configured for other tasks in this app.
    "claude-opus-4-6": Price("Claude Opus 4.6", 5.00, 25.00),
    "claude-opus-4-8": Price("Claude Opus 4.8", 5.00, 25.00),
    "claude-sonnet-5": Price("Claude Sonnet 5", 2.00, 10.00),
    "claude-haiku-4-5": Price("Claude Haiku 4.5", 1.00, 5.00),
}

# Models shown as "what this would have cost" alternatives, best first.
COMPARE_MODELS = ("claude-fable-5-2", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")

CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


def price_for(model: str) -> Optional[Price]:
    """Look up a model, tolerating dated IDs like claude-haiku-4-5-20251001."""
    if model in PRICES:
        return PRICES[model]
    for key, price in PRICES.items():
        if model.startswith(key + "-"):
            return price
    return None


def cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> Optional[float]:
    """Dollar cost of one call, or None for a model without a known price."""
    p = price_for(model)
    if p is None:
        return None
    billed_input = (
        input_tokens
        + cache_creation_input_tokens * CACHE_WRITE_MULTIPLIER
        + cache_read_input_tokens * CACHE_READ_MULTIPLIER
    )
    return (billed_input * p.input + output_tokens * p.output) / 1_000_000


def call_record(step: str, response) -> dict:
    """One model call as stored with a generated text."""
    record = {
        "step": step,
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "cache_creation_input_tokens": getattr(response, "cache_creation_input_tokens", 0),
        "cache_read_input_tokens": getattr(response, "cache_read_input_tokens", 0),
    }
    record["cost"] = cost(
        record["model"],
        record["input_tokens"],
        record["output_tokens"],
        record["cache_creation_input_tokens"],
        record["cache_read_input_tokens"],
    )
    return record


def summarize(calls: list[dict]) -> dict:
    """Total cost of a list of call records, plus estimates on other models."""
    known = [c for c in calls if c.get("cost") is not None]
    total = sum(c["cost"] for c in known) if known else None
    estimates = []
    for model in COMPARE_MODELS:
        est = sum(
            cost(model, c["input_tokens"], c["output_tokens"],
                 c.get("cache_creation_input_tokens", 0), c.get("cache_read_input_tokens", 0)) or 0
            for c in calls
        )
        estimates.append({"model": model, "label": PRICES[model].label, "cost": est})
    return {
        "calls": calls,
        "total_cost": total,
        "input_tokens": sum(c["input_tokens"] for c in calls),
        "output_tokens": sum(c["output_tokens"] for c in calls),
        "estimates": estimates,
    }
