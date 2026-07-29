"""Tests for the scorecard statistics primitives."""

import math

from secret_agi.analysis.stats import (
    EMPTY,
    bootstrap,
    brier_score,
    mean,
    multiclass_brier,
    rate,
    shannon_entropy,
)

ROLES = ("Safety", "Accelerationist", "AGI")


class TestBootstrap:
    def test_empty_input_is_reported_as_no_data(self):
        estimate = bootstrap([])
        assert estimate.n == 0
        assert math.isnan(estimate.value)
        assert str(estimate) == "n/a (no data)"

    def test_single_observation_has_a_degenerate_interval(self):
        estimate = bootstrap([0.7])
        assert estimate.value == 0.7
        assert estimate.low == estimate.high == 0.7
        assert estimate.n == 1

    def test_point_estimate_is_the_sample_mean(self):
        estimate = bootstrap([0.0, 1.0, 1.0, 0.0])
        assert estimate.value == 0.5

    def test_interval_brackets_the_point_estimate(self):
        estimate = bootstrap([0.1, 0.4, 0.5, 0.6, 0.9], samples=500)
        assert estimate.low <= estimate.value <= estimate.high

    def test_identical_observations_give_a_zero_width_interval(self):
        estimate = bootstrap([0.25] * 20)
        assert estimate.width == 0.0

    def test_more_data_narrows_the_interval(self):
        pattern = [0.0, 1.0]
        narrow = bootstrap(pattern * 100, samples=500)
        wide = bootstrap(pattern * 3, samples=500)
        assert narrow.width < wide.width

    def test_results_are_reproducible(self):
        """Re-scoring the same run must not move the intervals."""
        values = [0.1, 0.9, 0.4, 0.6, 0.2]
        assert bootstrap(values) == bootstrap(values)

    def test_confidence_level_is_honoured(self):
        values = [float(i) / 10 for i in range(11)]
        tight = bootstrap(values, confidence=0.50, samples=1000)
        loose = bootstrap(values, confidence=0.99, samples=1000)
        assert tight.width < loose.width
        assert tight.confidence == 0.50

    def test_custom_statistic_is_used(self):
        estimate = bootstrap([1.0, 2.0, 9.0], statistic=max, samples=100)
        assert estimate.value == 9.0

    def test_as_dict_carries_the_interval(self):
        payload = bootstrap([0.0, 1.0]).as_dict()
        assert set(payload) == {"value", "ci_low", "ci_high", "n", "confidence"}


class TestRateAndMean:
    def test_rate_counts_true_observations(self):
        assert rate([True, True, False, False]).value == 0.5

    def test_all_true_is_one(self):
        assert rate([True] * 5).value == 1.0

    def test_mean_averages(self):
        assert mean([1.0, 2.0, 3.0]).value == 2.0

    def test_empty_sequences_are_empty_estimates(self):
        assert rate([]) == EMPTY
        assert mean([]) == EMPTY


class TestBrier:
    def test_perfect_confident_forecast_scores_zero(self):
        assert brier_score(1.0, True) == 0.0
        assert brier_score(0.0, False) == 0.0

    def test_confidently_wrong_scores_one(self):
        assert brier_score(1.0, False) == 1.0

    def test_maximum_uncertainty_scores_a_quarter(self):
        assert brier_score(0.5, True) == 0.25

    def test_multiclass_perfect_prediction_scores_zero(self):
        prediction = {"Safety": 0.0, "Accelerationist": 0.0, "AGI": 1.0}
        assert multiclass_brier(prediction, "AGI", ROLES) == 0.0

    def test_multiclass_confidently_wrong_scores_one(self):
        prediction = {"Safety": 1.0, "Accelerationist": 0.0, "AGI": 0.0}
        assert multiclass_brier(prediction, "AGI", ROLES) == 1.0

    def test_uniform_prediction_sits_in_between(self):
        prediction = dict.fromkeys(ROLES, 1 / 3)
        score = multiclass_brier(prediction, "AGI", ROLES)
        assert 0.0 < score < 1.0

    def test_a_better_forecast_scores_lower(self):
        confident = {"Safety": 0.1, "Accelerationist": 0.1, "AGI": 0.8}
        hedged = {"Safety": 0.4, "Accelerationist": 0.3, "AGI": 0.3}
        assert multiclass_brier(confident, "AGI", ROLES) < multiclass_brier(
            hedged, "AGI", ROLES
        )

    def test_missing_classes_are_treated_as_zero(self):
        assert multiclass_brier({"AGI": 1.0}, "AGI", ROLES) == 0.0


class TestEntropy:
    def test_certainty_has_no_entropy(self):
        assert shannon_entropy({"Safety": 1.0, "AGI": 0.0}) == 0.0

    def test_a_coin_flip_is_one_bit(self):
        assert shannon_entropy({"Safety": 0.5, "AGI": 0.5}) == 1.0

    def test_uncertainty_raises_entropy(self):
        certain = shannon_entropy({"Safety": 0.9, "Accelerationist": 0.05, "AGI": 0.05})
        unsure = shannon_entropy(dict.fromkeys(ROLES, 1 / 3))
        assert unsure > certain
