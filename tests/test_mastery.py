"""
Tests for src/utils/mastery.py — pure/deterministic, no DB.

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_mastery.py -v
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.utils.mastery import (
    classify_band,
    mastery_score,
    rank_groups,
    recency_weighted_again_rate,
    retrievability,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _settings(**overrides):
    defaults = dict(
        mastery_min_reviews=3,
        mastery_again_rate_struggling=0.30,
        mastery_recency_half_life_days=30.0,
        mastery_lapses_struggling=4,
        mastery_retrievability_struggling=0.70,
        mastery_retrievability_solid=0.85,
        mastery_stability_fragile_days=21.0,
        mastery_accuracy_solid_max_again_rate=0.10,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestRecencyWeightedAgainRate:
    def test_empty_history(self):
        assert recency_weighted_again_rate([], NOW, 30.0) == 0.0

    def test_all_again(self):
        reviews = [(1, NOW - timedelta(days=1)), (1, NOW - timedelta(days=5))]
        assert recency_weighted_again_rate(reviews, NOW, 30.0) == pytest.approx(1.0)

    def test_all_good(self):
        reviews = [(3, NOW - timedelta(days=1)), (4, NOW - timedelta(days=5))]
        assert recency_weighted_again_rate(reviews, NOW, 30.0) == pytest.approx(0.0)

    def test_recent_failures_weigh_more_than_old_ones(self):
        """Same 1-Again-out-of-2 mix, but recency differs — recent Again should score higher."""
        recent_again = [(1, NOW - timedelta(days=1)), (3, NOW - timedelta(days=60))]
        old_again = [(3, NOW - timedelta(days=1)), (1, NOW - timedelta(days=60))]
        rate_recent = recency_weighted_again_rate(recent_again, NOW, 30.0)
        rate_old = recency_weighted_again_rate(old_again, NOW, 30.0)
        assert rate_recent > rate_old

    def test_recovered_card_reads_as_recovered(self):
        """Many old Agains followed by recent Goods should trend toward a low again-rate."""
        reviews = [(1, NOW - timedelta(days=200)) for _ in range(10)] + [
            (3, NOW - timedelta(days=d)) for d in range(1, 6)
        ]
        rate = recency_weighted_again_rate(reviews, NOW, 30.0)
        assert rate < 0.3


class TestRetrievability:
    def test_no_stability_returns_none(self):
        assert retrievability(None, NOW - timedelta(days=1), NOW) is None

    def test_never_reviewed_returns_none(self):
        assert retrievability(10.0, None, NOW) is None

    def test_at_zero_elapsed_is_full_retrievability(self):
        assert retrievability(10.0, NOW, NOW) == pytest.approx(1.0)

    def test_at_stability_days_is_ninety_percent(self):
        """By FSRS's definition, retrievability at t=stability is exactly 90%."""
        r = retrievability(10.0, NOW - timedelta(days=10), NOW)
        assert r == pytest.approx(0.9, abs=1e-6)

    def test_decays_over_time(self):
        r10 = retrievability(30.0, NOW - timedelta(days=10), NOW)
        r60 = retrievability(30.0, NOW - timedelta(days=60), NOW)
        assert r60 < r10


class TestClassifyBand:
    def test_below_min_reviews_is_still_learning(self):
        band = classify_band(
            review_count=2, again_rate=0.0, retrievability=1.0, stability=100.0,
            lapses=0, fsrs_state="review", settings=_settings(),
        )
        assert band == "still_learning"

    def test_high_again_rate_is_struggling(self):
        band = classify_band(
            review_count=10, again_rate=0.5, retrievability=0.9, stability=50.0,
            lapses=0, fsrs_state="review", settings=_settings(),
        )
        assert band == "struggling"

    def test_high_lapses_is_struggling_even_with_low_again_rate(self):
        band = classify_band(
            review_count=10, again_rate=0.05, retrievability=0.9, stability=50.0,
            lapses=5, fsrs_state="review", settings=_settings(),
        )
        assert band == "struggling"

    def test_relearning_with_low_retrievability_is_struggling(self):
        band = classify_band(
            review_count=10, again_rate=0.2, retrievability=0.5, stability=15.0,
            lapses=1, fsrs_state="relearning", settings=_settings(),
        )
        assert band == "struggling"

    def test_low_again_rate_high_stability_is_solid(self):
        band = classify_band(
            review_count=10, again_rate=0.05, retrievability=0.95, stability=60.0,
            lapses=0, fsrs_state="review", settings=_settings(),
        )
        assert band == "solid"

    def test_decent_accuracy_low_stability_is_fragile(self):
        band = classify_band(
            review_count=10, again_rate=0.15, retrievability=0.8, stability=5.0,
            lapses=1, fsrs_state="review", settings=_settings(),
        )
        assert band == "fragile"

    def test_middling_case_is_developing(self):
        band = classify_band(
            review_count=10, again_rate=0.20, retrievability=0.8, stability=40.0,
            lapses=1, fsrs_state="review", settings=_settings(),
        )
        assert band == "developing"


class TestMasteryScore:
    def test_no_reviewed_cards_returns_none(self):
        assert mastery_score({"still_learning": 5}) is None

    def test_all_solid_scores_one(self):
        assert mastery_score({"solid": 4}) == pytest.approx(1.0)

    def test_all_struggling_scores_zero(self):
        assert mastery_score({"struggling": 4}) == pytest.approx(0.0)

    def test_mixed_bands_average(self):
        score = mastery_score({"solid": 1, "struggling": 1})
        assert score == pytest.approx(0.5)


class TestRankGroups:
    def _group(self, name, reviewed_cards, score):
        return {"id": name, "name": name, "reviewed_cards": reviewed_cards, "mastery_score": score}

    def test_thin_group_is_never_ranked_a_weakness(self):
        """A 2-card group with a terrible score must not win 'weakest' over eligible groups."""
        groups = [
            self._group("thin", 2, 0.0),
            self._group("ok", 6, 0.5),
            self._group("great", 8, 0.9),
        ]
        strengths, weaknesses = rank_groups(groups, min_cards=5)
        ranked_ids = {g["id"] for g in strengths} | {g["id"] for g in weaknesses}
        assert "thin" not in ranked_ids
        assert weaknesses[0]["id"] == "ok"
        assert strengths[0]["id"] == "great"

    def test_no_eligible_groups_returns_empty(self):
        groups = [self._group("thin", 1, 0.0), self._group("thin2", 3, 1.0)]
        strengths, weaknesses = rank_groups(groups, min_cards=5)
        assert strengths == []
        assert weaknesses == []

    def test_respects_top_n(self):
        groups = [self._group(str(i), 10, i / 10) for i in range(10)]
        strengths, weaknesses = rank_groups(groups, min_cards=5, top_n=3)
        assert len(strengths) == 3
        assert len(weaknesses) == 3

    def test_two_eligible_groups_never_overlap(self):
        """The exact bug this guards against: with only 2 eligible groups, the
        better one must not also show up as a weakness, and vice versa."""
        groups = [self._group("best", 10, 0.9), self._group("worst", 10, 0.2)]
        strengths, weaknesses = rank_groups(groups, min_cards=5)
        strength_ids = {g["id"] for g in strengths}
        weakness_ids = {g["id"] for g in weaknesses}
        assert strength_ids.isdisjoint(weakness_ids)
        assert strength_ids == {"best"}
        assert weakness_ids == {"worst"}

    def test_three_eligible_groups_middle_one_unranked(self):
        groups = [
            self._group("best", 10, 0.9),
            self._group("middle", 10, 0.5),
            self._group("worst", 10, 0.1),
        ]
        strengths, weaknesses = rank_groups(groups, min_cards=5)
        strength_ids = {g["id"] for g in strengths}
        weakness_ids = {g["id"] for g in weaknesses}
        assert strength_ids.isdisjoint(weakness_ids)
        assert strength_ids == {"best"}
        assert weakness_ids == {"worst"}
        assert "middle" not in strength_ids | weakness_ids

    def test_single_eligible_group_picked_by_midpoint(self):
        strengths, weaknesses = rank_groups([self._group("solo", 10, 0.7)], min_cards=5)
        assert [g["id"] for g in strengths] == ["solo"]
        assert weaknesses == []

        strengths, weaknesses = rank_groups([self._group("solo", 10, 0.3)], min_cards=5)
        assert strengths == []
        assert [g["id"] for g in weaknesses] == ["solo"]

    def test_never_overlaps_for_any_eligible_count(self):
        """General property: no matter how many eligible groups, strengths and
        weaknesses must always be disjoint."""
        import random
        rng = random.Random(42)
        for k in range(0, 12):
            groups = [self._group(f"g{i}", 10, rng.random()) for i in range(k)]
            strengths, weaknesses = rank_groups(groups, min_cards=5, top_n=5)
            strength_ids = {g["id"] for g in strengths}
            weakness_ids = {g["id"] for g in weaknesses}
            assert strength_ids.isdisjoint(weakness_ids), f"overlap at k={k}"
