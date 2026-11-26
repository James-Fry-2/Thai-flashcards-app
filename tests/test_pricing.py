"""Tests for src/llm/pricing.py."""
import pytest

from src.llm import pricing


def test_cost_with_cache_tokens():
    # 1000 input + 1000 cache-write (x1.25) + 1000 cache-read (x0.1) = 2350 billed input
    c = pricing.cost("claude-opus-5-5", 1000, 1000, 1000, 1000)
    assert c == pytest.approx((2350 * 4 + 1000 * 20) / 1e6)


def test_dated_model_ids_and_unknown_models():
    assert pricing.price_for("claude-haiku-4-5-20251001").label == "Claude Haiku 4.5"
    assert pricing.cost("some-other-model", 10, 10) is None


def test_summarize_skips_unpriced_calls_in_total():
    calls = [
        {"step": "a", "model": "claude-opus-5-5", "input_tokens": 1_000_000, "output_tokens": 0, "cost": 4.0},
        {"step": "b", "model": "mystery", "input_tokens": 0, "output_tokens": 0, "cost": None},
    ]
    s = pricing.summarize(calls)
    assert s["total_cost"] == 4.0
    assert {e["model"] for e in s["estimates"]} == set(pricing.COMPARE_MODELS)
