"""Unit tests for the CDMX-midnight prediction cutoff (app.api.predictions._predictable).

Rule: a match is open for predictions until 00:00 America/Mexico_City (fixed UTC-6,
Mexico abolished DST in 2022) of the *calendar day the match is played*. So you must
submit before midnight CDMX the day before. `now` is always tz-aware UTC.

`_predictable` only reads attributes (finished, round_code, home_team_id,
away_team_id, kickoff_at) so a lightweight stand-in object is sufficient — no DB.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from app.api.predictions import _predictable, CDMX


def _match(**kw):
    base = dict(
        finished=False,
        round_code="group",
        home_team_id=1,
        away_team_id=2,
        kickoff_at=datetime(2026, 6, 11, 19, 0, tzinfo=timezone.utc),
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestCDMXConstant:
    def test_cdmx_is_fixed_utc_minus_6(self):
        assert CDMX.utcoffset(None) == timedelta(hours=-6)


class TestCutoffWindow:
    """Match kicks off 2026-06-11 19:00 UTC = 13:00 CDMX → CDMX day 2026-06-11 →
    cutoff = 2026-06-11 00:00 CDMX = 2026-06-11 06:00 UTC."""

    def test_open_well_before_cutoff(self):
        now = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
        assert _predictable(_match(), now) is True

    def test_open_just_before_cutoff(self):
        # 05:59 UTC on match day is still before 06:00 UTC cutoff
        now = datetime(2026, 6, 11, 5, 59, tzinfo=timezone.utc)
        assert _predictable(_match(), now) is True

    def test_closed_at_exact_cutoff(self):
        # 06:00 UTC == 00:00 CDMX → not strictly before → closed
        now = datetime(2026, 6, 11, 6, 0, tzinfo=timezone.utc)
        assert _predictable(_match(), now) is False

    def test_closed_after_cutoff(self):
        now = datetime(2026, 6, 11, 7, 0, tzinfo=timezone.utc)
        assert _predictable(_match(), now) is False

    def test_closed_at_kickoff(self):
        now = datetime(2026, 6, 11, 19, 0, tzinfo=timezone.utc)
        assert _predictable(_match(), now) is False


class TestTimezoneBoundary:
    """A match late at night UTC can belong to the *previous* CDMX day."""

    def test_after_midnight_utc_belongs_to_previous_cdmx_day(self):
        # kickoff 2026-06-11 02:00 UTC = 2026-06-10 20:00 CDMX → CDMX day is the 10th
        # → cutoff = 2026-06-10 00:00 CDMX = 2026-06-10 06:00 UTC
        m = _match(kickoff_at=datetime(2026, 6, 11, 2, 0, tzinfo=timezone.utc))
        # still open just before that earlier cutoff
        assert _predictable(m, datetime(2026, 6, 10, 5, 0, tzinfo=timezone.utc)) is True
        # closed once the 10th's midnight CDMX has passed
        assert _predictable(m, datetime(2026, 6, 10, 6, 0, tzinfo=timezone.utc)) is False

    def test_naive_kickoff_treated_as_utc(self):
        naive = _match(kickoff_at=datetime(2026, 6, 11, 19, 0))  # no tzinfo
        # same as the tz-aware UTC case: open before 06:00 UTC, closed after
        assert _predictable(naive, datetime(2026, 6, 11, 5, 0, tzinfo=timezone.utc)) is True
        assert _predictable(naive, datetime(2026, 6, 11, 7, 0, tzinfo=timezone.utc)) is False


class TestNonTimeGuards:
    def test_finished_match_never_predictable(self):
        m = _match(finished=True, kickoff_at=datetime(2099, 1, 1, tzinfo=timezone.utc))
        assert _predictable(m, datetime(2026, 6, 1, tzinfo=timezone.utc)) is False

    def test_unresolved_knockout_not_predictable(self):
        # knockout slot whose teams aren't decided yet
        m = _match(round_code="r16", home_team_id=None, away_team_id=None,
                   kickoff_at=datetime(2099, 1, 1, tzinfo=timezone.utc))
        assert _predictable(m, datetime(2026, 6, 1, tzinfo=timezone.utc)) is False

    def test_resolved_knockout_follows_cutoff(self):
        m = _match(round_code="r16",
                   kickoff_at=datetime(2026, 6, 11, 19, 0, tzinfo=timezone.utc))
        assert _predictable(m, datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)) is True

    def test_group_match_with_null_teams_still_predictable(self):
        # the unresolved-slot guard applies to non-group rounds only
        m = _match(home_team_id=None, away_team_id=None)
        assert _predictable(m, datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)) is True

    def test_none_kickoff_is_open(self):
        # no scheduled time yet → cannot have passed a cutoff → open
        m = _match(kickoff_at=None)
        assert _predictable(m, datetime(2026, 6, 1, tzinfo=timezone.utc)) is True
