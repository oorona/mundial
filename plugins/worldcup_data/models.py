"""
worldcup_data — read-mostly ORM models mapping the ingest-owned WC2026 reference
tables, plus the cross-cutting helper functions shared by the other plugins
(predictions / leaderboard / live_tracker).

These tables live in the SAME `mundial` schema the framework backend connects to
(search_path = effective_schema = DB_USER = "mundial"), so they need no schema
qualification. They are created/owned by the `ingest/` tool — NOT by Alembic — so
there is no CREATE TABLE migration for them. (The plugin's migration only ADDs the
penalty-shootout columns to `matches`.)

`Base`, `Column`, the SQLAlchemy types and `func` are already imported at the top of
backend/app/models.py, where this content is appended at install time. We re-import
the names we use (Python dedups) and reference `Base` from module scope.
"""

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, select
from sqlalchemy.ext.asyncio import AsyncSession


# ── Reference tables (global, read-mostly) ──────────────────────────────────────
class WCStadium(Base):  # noqa: F821  (Base defined in app/models.py)
    __tablename__ = "stadiums"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    name_en = Column(String(200))
    fifa_name = Column(String(200))
    city_en = Column(String(120))
    country_en = Column(String(120))
    capacity = Column(Integer)
    region = Column(String(60))


class WCTeam(Base):  # noqa: F821
    __tablename__ = "teams"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    name_en = Column(String(120))
    flag = Column(Text)                       # repo-relative path e.g. "flags/mx.png"
    fifa_code = Column(String(3))
    iso2 = Column(String(8))
    group_letter = Column("group", String(1))
    coach = Column(String(120))
    nickname = Column(String(120))
    confederation = Column(String(20))
    wc_appearances = Column(Integer)
    wc_first_year = Column(Integer)
    wc_best_result = Column(String(255))
    fifa_ranking = Column(Integer)
    wikipedia_url = Column(Text)


class WCGroupStanding(Base):  # noqa: F821
    __tablename__ = "group_standings"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    group_letter = Column("group", String(1))
    team_id = Column(Integer, ForeignKey("teams.id"))
    mp = Column(Integer)
    w = Column(Integer)
    d = Column(Integer)
    l = Column(Integer)
    gf = Column(Integer)
    ga = Column(Integer)
    gd = Column(Integer)
    pts = Column(Integer)


class WCMatch(Base):  # noqa: F821
    __tablename__ = "matches"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    home_team_id = Column(Integer, ForeignKey("teams.id"))
    away_team_id = Column(Integer, ForeignKey("teams.id"))
    home_team_label = Column(String(80))
    away_team_label = Column(String(80))
    home_score = Column(Integer)
    away_score = Column(Integer)
    home_pens = Column(Integer)               # added by the worldcup_data migration
    away_pens = Column(Integer)
    group_code = Column("group", String(8))
    matchday = Column(Integer)
    round_code = Column("type", String(10))   # group/r32/r16/qf/sf/third/final
    stadium_id = Column(Integer, ForeignKey("stadiums.id"))
    kickoff_at = Column(DateTime(timezone=True))
    finished = Column(Boolean)
    time_elapsed = Column(String(20))


class WCPlayer(Base):  # noqa: F821
    __tablename__ = "players"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"))
    name = Column(String(120))
    position = Column(String(40))


# ── Flag helper ─────────────────────────────────────────────────────────────────
def flag_url(team_flag: str | None, base: str = "") -> str | None:
    """Build a flag URL from a team's stored `flag` path ("flags/mx.png").

    `base` empty → returns a root-relative URL ("/flags/mx.png") for same-origin web
    use; a base (frontend origin) → absolute URL for Discord embeds. Flags are served
    by Next.js from frontend/public/flags/<code>.png.
    """
    if not team_flag:
        return None
    rel = team_flag.lstrip("/")
    base = (base or "").rstrip("/")
    return f"{base}/{rel}" if base else f"/{rel}"


# ── Scoring engine (Kicktipp) — shared by predictions + live_tracker ─────────────
def score_prediction(
    pred_h, pred_a, act_h, act_a,
    w_exact: int = 4, w_diff: int = 3, w_tend: int = 2,
    ko_mult: float = 2.0, is_knockout: bool = False,
) -> int:
    """Kicktipp-style points for one prediction against an actual result.

    Participating earns a 1-pt floor (the caller only invokes this for a pick the
    user actually submitted on a finished match); correctness is added on top —
    exact score → +w_exact; same (nonzero) goal difference → +w_diff; same tendency
    (incl. draw) → +w_tend; wrong → +0. Knockout multiplies the correctness part.
    So wrong=1, tendency=1+w_tend, diff=1+w_diff, exact=1+w_exact (KO: ×ko_mult on
    the correctness). Non-participants have no row → 0 (handled by the caller).
    """
    if pred_h is None or pred_a is None or act_h is None or act_a is None:
        return 0
    pred_h, pred_a, act_h, act_a = int(pred_h), int(pred_a), int(act_h), int(act_a)
    if pred_h == act_h and pred_a == act_a:
        base = w_exact
    elif (pred_h - pred_a) == (act_h - act_a) and (act_h - act_a) != 0:
        base = w_diff
    elif _sign(pred_h - pred_a) == _sign(act_h - act_a):
        base = w_tend
    else:
        base = 0
    correctness = int(round(base * float(ko_mult))) if (base and is_knockout) else base
    return 1 + correctness


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


def scoring_rules(weights: dict | None = None) -> dict:
    """Human-readable scoring rules payload (used by the Rules page + /mundial reglas)."""
    w = weights or {}
    return {
        "weight_participation": 1,
        "weight_exact": w.get("weight_exact", 4),
        "weight_diff": w.get("weight_diff", 3),
        "weight_tendency": w.get("weight_tendency", 2),
        "knockout_multiplier": w.get("knockout_multiplier", 2),
        "lock_lead_minutes": w.get("lock_lead_minutes", 0),
    }


# ── Standings recompute (shared) ────────────────────────────────────────────────
async def recompute_group_standings(session: AsyncSession, group_letter: str) -> None:
    """Recompute one group's standings from all finished group matches (full recompute,
    idempotent). 3/1/0 points; updates mp/w/d/l/gf/ga/gd/pts. Caller commits."""
    matches = (await session.execute(
        select(WCMatch).where(
            WCMatch.round_code == "group",
            WCMatch.group_code == group_letter,
            WCMatch.finished.is_(True),
        )
    )).scalars().all()

    tally: dict[int, dict] = {}

    def _row(tid: int) -> dict:
        return tally.setdefault(tid, dict(mp=0, w=0, d=0, l=0, gf=0, ga=0))

    for m in matches:
        if m.home_team_id is None or m.away_team_id is None:
            continue
        if m.home_score is None or m.away_score is None:
            continue
        h, a = _row(m.home_team_id), _row(m.away_team_id)
        h["mp"] += 1; a["mp"] += 1
        h["gf"] += m.home_score; h["ga"] += m.away_score
        a["gf"] += m.away_score; a["ga"] += m.home_score
        if m.home_score > m.away_score:
            h["w"] += 1; a["l"] += 1
        elif m.home_score < m.away_score:
            a["w"] += 1; h["l"] += 1
        else:
            h["d"] += 1; a["d"] += 1

    standings = (await session.execute(
        select(WCGroupStanding).where(WCGroupStanding.group_letter == group_letter)
    )).scalars().all()

    for s in standings:
        t = tally.get(s.team_id, dict(mp=0, w=0, d=0, l=0, gf=0, ga=0))
        s.mp = t["mp"]; s.w = t["w"]; s.d = t["d"]; s.l = t["l"]
        s.gf = t["gf"]; s.ga = t["ga"]; s.gd = t["gf"] - t["ga"]
        s.pts = t["w"] * 3 + t["d"]

    await session.flush()


def rank_standings(rows: list) -> list:
    """Order WCGroupStanding rows by pts, gd, gf (descending). Head-to-head and
    fair-play tiebreaks are a later refinement; this is the display/ranking order."""
    return sorted(rows, key=lambda s: (s.pts or 0, s.gd or 0, s.gf or 0), reverse=True)


# ── Bracket resolution (shared) ─────────────────────────────────────────────────
def match_winner_loser(m: "WCMatch"):
    """Return (winner_team_id, loser_team_id) for a finished knockout match, using
    penalties to break a level score. Returns (None, None) if undecided."""
    if not m or not m.finished or m.home_team_id is None or m.away_team_id is None:
        return (None, None)
    if m.home_score is None or m.away_score is None:
        return (None, None)
    if m.home_score > m.away_score:
        return (m.home_team_id, m.away_team_id)
    if m.away_score > m.home_score:
        return (m.away_team_id, m.home_team_id)
    # Level → penalties
    if m.home_pens is not None and m.away_pens is not None and m.home_pens != m.away_pens:
        if m.home_pens > m.away_pens:
            return (m.home_team_id, m.away_team_id)
        return (m.away_team_id, m.home_team_id)
    return (None, None)


async def resolve_bracket(session: AsyncSession) -> int:
    """Fill knockout match team FKs from their `*_team_label` slots as results land.

    Resolves: "Winner Group X" / "Runner-up Group X" (from a fully-finished group's
    ranked standings) and "Winner Match N" / "Loser Match N" (from finished match N).
    Best-thirds slots ("3rd Group A/B/C/D…") are completed in the live_tracker phase.
    Only fills currently-NULL FKs (idempotent). Returns the number of slots filled.
    Caller commits."""
    # Group winners / runners-up, only for groups whose matches are all finished.
    group_first: dict[str, int] = {}
    group_second: dict[str, int] = {}
    for letter in [chr(c) for c in range(ord("A"), ord("L") + 1)]:
        gmatches = (await session.execute(
            select(WCMatch).where(WCMatch.round_code == "group", WCMatch.group_code == letter)
        )).scalars().all()
        if not gmatches or not all(m.finished for m in gmatches):
            continue
        rows = (await session.execute(
            select(WCGroupStanding).where(WCGroupStanding.group_letter == letter)
        )).scalars().all()
        ranked = rank_standings(rows)
        if len(ranked) >= 2:
            group_first[letter] = ranked[0].team_id
            group_second[letter] = ranked[1].team_id

    def resolve_label(label: str | None):
        if not label:
            return None
        s = label.strip()
        low = s.lower()
        if low.startswith("winner group "):
            return group_first.get(s[-1].upper())
        if low.startswith("runner-up group ") or low.startswith("runner up group "):
            return group_second.get(s[-1].upper())
        return None  # match-based + best-thirds handled below / later

    ko = (await session.execute(
        select(WCMatch).where(WCMatch.round_code != "group")
    )).scalars().all()
    by_id = {m.id: m for m in ko}

    def resolve_match_label(label: str | None):
        if not label:
            return None
        s = label.strip()
        low = s.lower()
        if low.startswith("winner match ") or low.startswith("loser match "):
            try:
                mid = int("".join(ch for ch in s if ch.isdigit()))
            except ValueError:
                return None
            src = by_id.get(mid)
            if src is None:
                return None
            win, lose = match_winner_loser(src)
            return win if low.startswith("winner") else lose
        return None

    filled = 0
    for m in ko:
        if m.home_team_id is None:
            tid = resolve_label(m.home_team_label) or resolve_match_label(m.home_team_label)
            if tid:
                m.home_team_id = tid
                filled += 1
        if m.away_team_id is None:
            tid = resolve_label(m.away_team_label) or resolve_match_label(m.away_team_label)
            if tid:
                m.away_team_id = tid
                filled += 1

    if filled:
        await session.flush()
    return filled
