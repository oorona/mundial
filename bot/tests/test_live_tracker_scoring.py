"""Parity tests for the bot-side scoring mirror (cogs.live_tracker._score).

`_score` is a hand-maintained re-implementation of the backend's
`app.models.score_prediction` (the bot process has no backend ORM on its path).
The two MUST agree on every input, or a user's leaderboard points will differ
depending on whether they were computed by the live worker or the API. These tests
pin `_score` to the same point table the backend test asserts, so drift between the
two implementations fails CI on both sides.

Argument order: _score(ph, pa, ah, aa, we, wd, wt, km, is_ko)
  ph/pa = predicted home/away, ah/aa = actual home/away,
  we/wd/wt = exact/diff/tendency weights, km = knockout multiplier, is_ko = knockout?
"""
import pytest
from cogs.live_tracker import _score

# Default weights, mirroring backend score_prediction defaults.
WE, WD, WT, KM = 4, 3, 2, 2.0


def s(ph, pa, ah, aa, is_ko=False):
    return _score(ph, pa, ah, aa, WE, WD, WT, KM, is_ko)


class TestGroupStageParity:
    def test_exact(self):
        assert s(2, 1, 2, 1) == 5

    def test_exact_draw(self):
        assert s(0, 0, 0, 0) == 5

    def test_diff(self):
        assert s(2, 1, 3, 2) == 4

    def test_tendency(self):
        assert s(3, 0, 1, 0) == 3

    def test_draw_tendency_not_diff(self):
        assert s(1, 1, 2, 2) == 3

    def test_wrong_earns_floor(self):
        assert s(2, 0, 0, 1) == 1

    def test_opposite_sign_same_magnitude_is_wrong(self):
        assert s(0, 1, 1, 0) == 1


class TestKnockoutParity:
    def test_ko_exact(self):
        assert s(2, 1, 2, 1, is_ko=True) == 9

    def test_ko_diff(self):
        assert s(2, 1, 3, 2, is_ko=True) == 7

    def test_ko_tendency(self):
        assert s(3, 0, 1, 0, is_ko=True) == 5

    def test_ko_wrong_not_multiplied(self):
        assert s(2, 0, 0, 1, is_ko=True) == 1


class TestNoneGuards:
    @pytest.mark.parametrize("args", [
        (None, 1, 2, 1),
        (2, None, 2, 1),
        (2, 1, None, 1),
        (2, 1, 2, None),
        (None, None, None, None),
    ])
    def test_none_returns_zero(self, args):
        assert s(*args) == 0


class TestStringCoercion:
    def test_string_inputs(self):
        assert s("2", "1", "2", "1") == 5


class TestFullTableParity:
    """The canonical point table both engines must reproduce."""
    EXPECTED = {
        # (ph, pa, ah, aa, is_ko): points
        (2, 1, 2, 1, False): 5,   # exact
        (2, 1, 3, 2, False): 4,   # diff
        (3, 0, 1, 0, False): 3,   # tendency
        (2, 0, 0, 1, False): 1,   # wrong → floor
        (2, 1, 2, 1, True): 9,    # KO exact
        (2, 1, 3, 2, True): 7,    # KO diff
        (3, 0, 1, 0, True): 5,    # KO tendency
        (2, 0, 0, 1, True): 1,    # KO wrong → floor
    }

    def test_table(self):
        for (ph, pa, ah, aa, ko), pts in self.EXPECTED.items():
            assert s(ph, pa, ah, aa, ko) == pts, f"{(ph, pa, ah, aa, ko)} expected {pts}"
