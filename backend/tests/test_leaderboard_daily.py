"""Unit tests for leaderboard aggregation and the daily (yesterday-CDMX) window.

Covers `_aggregate` (the shared per-user reducer used by both the global and daily
boards) and `_cdmx_yesterday_window` (the bounds the daily endpoint filters matches
by). Both are pure; aggregation reads attributes off prediction/match stand-ins.

Key semantics under participation scoring:
- `points` sums every prediction's points (incl. the 1-pt participation floor).
- `aciertos` counts only picks that BEAT the floor (points > 1) — a genuinely
  correct pick, not mere participation.
- `exactos` counts exact scorelines on finished matches.
- `jugados` counts finished matches the user predicted on.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from app.api.leaderboard import _aggregate, _cdmx_yesterday_window, CDMX


def _pred(user_id, points, match_id, pred_home, pred_away, username=None):
    return SimpleNamespace(
        user_id=user_id, points=points, match_id=match_id,
        pred_home=pred_home, pred_away=pred_away, username=username,
    )


def _finished(mid, home, away):
    return SimpleNamespace(id=mid, finished=True, home_score=home, away_score=away)


def _unfinished(mid):
    return SimpleNamespace(id=mid, finished=False, home_score=None, away_score=None)


class TestAggregateBasics:
    def test_empty(self):
        assert _aggregate([], {}) == []

    def test_single_exact_pick(self):
        matches = {1: _finished(1, 2, 1)}
        preds = [_pred(100, 5, 1, 2, 1, username="ana")]
        rows = _aggregate(preds, matches)
        assert len(rows) == 1
        r = rows[0]
        assert r["points"] == 5
        assert r["exactos"] == 1
        assert r["aciertos"] == 1
        assert r["jugados"] == 1
        assert r["position"] == 1
        assert r["username"] == "ana"

    def test_participation_floor_is_not_an_acierto(self):
        # wrong-but-submitted pick: points == 1 (floor) → counts as jugado but NOT acierto
        matches = {1: _finished(1, 0, 3)}
        preds = [_pred(100, 1, 1, 2, 0)]
        r = _aggregate(preds, matches)[0]
        assert r["points"] == 1
        assert r["jugados"] == 1
        assert r["aciertos"] == 0
        assert r["exactos"] == 0

    def test_correct_but_not_exact_is_acierto_not_exacto(self):
        matches = {1: _finished(1, 3, 2)}
        preds = [_pred(100, 4, 1, 2, 1)]  # right tendency/diff, wrong scoreline
        r = _aggregate(preds, matches)[0]
        assert r["aciertos"] == 1
        assert r["exactos"] == 0

    def test_points_accumulate_across_matches(self):
        matches = {1: _finished(1, 2, 1), 2: _finished(2, 0, 0)}
        preds = [
            _pred(100, 5, 1, 2, 1),  # exact
            _pred(100, 1, 2, 1, 0),  # wrong, floor only
        ]
        r = _aggregate(preds, matches)[0]
        assert r["points"] == 6
        assert r["jugados"] == 2
        assert r["aciertos"] == 1


class TestAggregateUnfinishedAndMissing:
    def test_unfinished_match_counts_points_but_not_jugados(self):
        # points get summed regardless, but jugados/aciertos/exactos require a
        # finished match with both scores present
        matches = {1: _unfinished(1)}
        preds = [_pred(100, 1, 1, 2, 1)]
        r = _aggregate(preds, matches)[0]
        assert r["points"] == 1
        assert r["jugados"] == 0
        assert r["aciertos"] == 0

    def test_pred_for_unknown_match(self):
        # a prediction whose match isn't in the dict still contributes points only
        r = _aggregate([_pred(100, 5, 999, 2, 1)], {})[0]
        assert r["points"] == 5
        assert r["jugados"] == 0

    def test_none_points_treated_as_zero(self):
        matches = {1: _finished(1, 2, 1)}
        r = _aggregate([_pred(100, None, 1, 0, 0)], matches)[0]
        assert r["points"] == 0
        assert r["jugados"] == 1
        assert r["aciertos"] == 0


class TestAggregateRankingAndNames:
    def test_sorted_by_points_desc(self):
        matches = {1: _finished(1, 2, 1), 2: _finished(2, 1, 0)}
        preds = [
            _pred(1, 1, 1, 0, 5, username="low"),
            _pred(2, 5, 1, 2, 1, username="high"),
        ]
        rows = _aggregate(preds, matches)
        assert [r["username"] for r in rows] == ["high", "low"]
        assert rows[0]["position"] == 1
        assert rows[1]["position"] == 2

    def test_tiebreak_points_then_exactos(self):
        # equal points, the one with more exactos ranks higher
        matches = {1: _finished(1, 2, 1), 2: _finished(2, 1, 0)}
        preds = [
            _pred(1, 5, 1, 2, 1, username="exact"),   # 5 pts, 1 exacto
            _pred(2, 5, 2, 9, 0, username="lucky"),   # 5 pts, 0 exacto (manual points)
        ]
        rows = _aggregate(preds, matches)
        assert rows[0]["username"] == "exact"

    def test_username_fallback_uses_last4_of_id(self):
        matches = {1: _finished(1, 2, 1)}
        r = _aggregate([_pred(123456, 5, 1, 2, 1, username=None)], matches)[0]
        assert r["username"] == "Jugador 3456"

    def test_username_picked_up_from_any_row(self):
        matches = {1: _finished(1, 2, 1), 2: _finished(2, 0, 0)}
        preds = [
            _pred(100, 1, 1, 0, 9, username=None),
            _pred(100, 5, 2, 0, 0, username="bob"),
        ]
        r = _aggregate(preds, matches)[0]
        assert r["username"] == "bob"


class TestYesterdayWindow:
    def test_returns_three_values(self):
        start, end, day = _cdmx_yesterday_window()
        assert isinstance(start, datetime)
        assert isinstance(end, datetime)

    def test_window_is_exactly_one_day(self):
        start, end, _ = _cdmx_yesterday_window()
        assert end - start == timedelta(days=1)

    def test_bounds_anchored_to_cdmx_midnight(self):
        start, end, day = _cdmx_yesterday_window()
        assert start.utcoffset() == timedelta(hours=-6)
        assert start.hour == 0 and start.minute == 0
        assert start.date() == day

    def test_day_is_in_the_past(self):
        # yesterday's CDMX date must be strictly before today's CDMX date
        start, end, day = _cdmx_yesterday_window()
        today_cdmx = datetime.now(CDMX).date()
        assert day < today_cdmx
        assert (today_cdmx - day) == timedelta(days=1)
