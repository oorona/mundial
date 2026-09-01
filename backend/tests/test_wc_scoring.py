"""Unit tests for the WC2026 Kicktipp scoring engine (app.models).

Covers `score_prediction` (participation floor + correctness on top, knockout
multiplier, None guards) and the `scoring_rules` payload. These are pure functions
shared by the predictions API and the live_tracker cog, so the same numbers must
hold everywhere a score is computed.
"""
import pytest
from app.models import score_prediction, scoring_rules, _sign


class TestSignHelper:
    def test_positive(self):
        assert _sign(5) == 1

    def test_negative(self):
        assert _sign(-3) == -1

    def test_zero(self):
        assert _sign(0) == 0


class TestScorePredictionGroupStage:
    """Default weights: exact=4, diff=3, tendency=2, participation floor=1."""

    def test_exact_score(self):
        # exact → 1 (participation) + 4 (exact) = 5
        assert score_prediction(2, 1, 2, 1) == 5

    def test_exact_draw(self):
        assert score_prediction(0, 0, 0, 0) == 5

    def test_goal_difference_nonzero(self):
        # predicted +1, actual +1, but not the exact scoreline → 1 + diff(3) = 4
        assert score_prediction(2, 1, 3, 2) == 4

    def test_tendency_only(self):
        # both home wins, different margin/score → 1 + tendency(2) = 3
        assert score_prediction(3, 0, 1, 0) == 3

    def test_draw_is_tendency_not_diff(self):
        # predicted draw, actual draw, different scoreline → tendency, NOT diff
        # (the diff branch excludes a zero goal difference) → 1 + 2 = 3
        assert score_prediction(1, 1, 2, 2) == 3

    def test_wrong_prediction_still_earns_floor(self):
        # predicted home win, away actually won → wrong → just the 1-pt floor
        assert score_prediction(2, 0, 0, 1) == 1

    def test_wrong_draw_vs_win(self):
        assert score_prediction(1, 1, 2, 0) == 1

    def test_diff_requires_same_sign(self):
        # predicted away by 1 (0-1), actual home by 1 (1-0): same |diff| but
        # opposite sign → must NOT score diff, it's just wrong → floor only
        assert score_prediction(0, 1, 1, 0) == 1


class TestScorePredictionKnockout:
    """Knockout rounds score the same as group rounds — the multiplier was
    removed; ko_mult/is_knockout are retained for signature stability only."""

    def test_ko_exact(self):
        assert score_prediction(2, 1, 2, 1, is_knockout=True) == 5

    def test_ko_diff(self):
        assert score_prediction(2, 1, 3, 2, is_knockout=True) == 4

    def test_ko_tendency(self):
        assert score_prediction(3, 0, 1, 0, is_knockout=True) == 3

    def test_ko_wrong_scores_floor(self):
        assert score_prediction(2, 0, 0, 1, is_knockout=True) == 1

    def test_custom_multiplier_ignored(self):
        # ko_mult no longer affects the score: diff → 1 + 3 = 4
        assert score_prediction(2, 1, 3, 2, ko_mult=1.5, is_knockout=True) == 4


class TestScorePredictionNoneGuards:
    """A None on either side means not-yet-scorable → 0 (no floor awarded)."""

    def test_pred_home_none(self):
        assert score_prediction(None, 1, 2, 1) == 0

    def test_pred_away_none(self):
        assert score_prediction(2, None, 2, 1) == 0

    def test_actual_home_none(self):
        assert score_prediction(2, 1, None, 1) == 0

    def test_actual_away_none(self):
        assert score_prediction(2, 1, 2, None) == 0

    def test_all_none(self):
        assert score_prediction(None, None, None, None) == 0


class TestScorePredictionCustomWeights:
    def test_custom_weights_applied(self):
        # exact with exact weight 10 → 1 + 10 = 11
        assert score_prediction(1, 0, 1, 0, w_exact=10, w_diff=5, w_tend=3) == 11

    def test_string_inputs_coerced(self):
        # callers may pass DB ints as strings; function int()-coerces
        assert score_prediction("2", "1", "2", "1") == 5


class TestScoringRules:
    def test_defaults_include_participation_floor(self):
        rules = scoring_rules()
        assert rules["weight_participation"] == 1
        assert rules["weight_exact"] == 4
        assert rules["weight_diff"] == 3
        assert rules["weight_tendency"] == 2
        assert rules["knockout_multiplier"] == 2

    def test_custom_weights_override(self):
        rules = scoring_rules({"weight_exact": 9, "knockout_multiplier": 3})
        assert rules["weight_exact"] == 9
        assert rules["knockout_multiplier"] == 3
        # participation floor is fixed, not overridable from weights
        assert rules["weight_participation"] == 1

    def test_none_weights_uses_defaults(self):
        assert scoring_rules(None)["weight_tendency"] == 2

    def test_ordering_floor_below_every_correctness_tier(self):
        # the design invariant: wrong(1) < tendency < diff < exact, all > 0
        wrong = score_prediction(2, 0, 0, 1)
        tendency = score_prediction(3, 0, 1, 0)
        diff = score_prediction(2, 1, 3, 2)
        exact = score_prediction(2, 1, 2, 1)
        assert 0 < wrong < tendency < diff < exact
