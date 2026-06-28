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
    (incl. draw) → +w_tend; wrong → +0. So wrong=1, tendency=1+w_tend, diff=1+w_diff,
    exact=1+w_exact. Knockout rounds score the same as group rounds (no multiplier).
    Non-participants have no row → 0 (handled by the caller). `ko_mult`/`is_knockout`
    are retained for signature stability but no longer affect the score.
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
    return 1 + int(base)


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


# ── FIFA Annex C: best-eight third-placed teams → R32 winner slots ───────────────
# Key: the 8 qualifying third-place GROUP letters, sorted. Value: the third-place
# group assigned to each winner slot, in winner-group order A,B,D,E,G,I,K,L. Source:
# FIFA Regulations for the FIFA World Cup 26, Annex C (495 combinations). Validated
# 2026-06-28: all C(12,8) combos present, none pairs a winner with its own group, and
# every column's group-set equals our seeded "3rd Group …" eligibility labels.
THIRD_PLACE_WINNER_ORDER = "ABDEGIKL"
THIRD_PLACE_TABLE = {
    "ABCDEFGH":"HGBCAFDE", "ABCDEFGI":"CGBDAFEI", "ABCDEFGJ":"CGBDAFEJ", "ABCDEFGK":"CGBDAFEK",
    "ABCDEFGL":"CGBDAFLE", "ABCDEFHI":"HEBCAFDI", "ABCDEFHJ":"HJBCAFDE", "ABCDEFHK":"HEBCAFDK",
    "ABCDEFHL":"HFBCADLE", "ABCDEFIJ":"CJBDAFEI", "ABCDEFIK":"CEBDAFIK", "ABCDEFIL":"CEBDAFLI",
    "ABCDEFJK":"CJBDAFEK", "ABCDEFJL":"CJBDAFLE", "ABCDEFKL":"CEBDAFLK", "ABCDEGHI":"HGBCADEI",
    "ABCDEGHJ":"HGBCADEJ", "ABCDEGHK":"HGBCADEK", "ABCDEGHL":"HGBCADLE", "ABCDEGIJ":"EGBCADIJ",
    "ABCDEGIK":"EGBCADIK", "ABCDEGIL":"EGBCADLI", "ABCDEGJK":"EGBCADJK", "ABCDEGJL":"EGBCADLJ",
    "ABCDEGKL":"EGBCADLK", "ABCDEHIJ":"HJBCADEI", "ABCDEHIK":"HEBCADIK", "ABCDEHIL":"HEBCADLI",
    "ABCDEHJK":"HJBCADEK", "ABCDEHJL":"HJBCADLE", "ABCDEHKL":"HEBCADLK", "ABCDEIJK":"EJBCADIK",
    "ABCDEIJL":"EJBCADLI", "ABCDEIKL":"EIBCADLK", "ABCDEJKL":"EJBCADLK", "ABCDFGHI":"HGBCAFDI",
    "ABCDFGHJ":"HGBCAFDJ", "ABCDFGHK":"HGBCAFDK", "ABCDFGHL":"CGBDAFLH", "ABCDFGIJ":"CGBDAFIJ",
    "ABCDFGIK":"CGBDAFIK", "ABCDFGIL":"CGBDAFLI", "ABCDFGJK":"CGBDAFJK", "ABCDFGJL":"CGBDAFLJ",
    "ABCDFGKL":"CGBDAFLK", "ABCDFHIJ":"HJBCAFDI", "ABCDFHIK":"HFBCADIK", "ABCDFHIL":"HFBCADLI",
    "ABCDFHJK":"HJBCAFDK", "ABCDFHJL":"CJBDAFLH", "ABCDFHKL":"HFBCADLK", "ABCDFIJK":"CJBDAFIK",
    "ABCDFIJL":"CJBDAFLI", "ABCDFIKL":"CIBDAFLK", "ABCDFJKL":"CJBDAFLK", "ABCDGHIJ":"HGBCADIJ",
    "ABCDGHIK":"HGBCADIK", "ABCDGHIL":"HGBCADLI", "ABCDGHJK":"HGBCADJK", "ABCDGHJL":"HGBCADLJ",
    "ABCDGHKL":"HGBCADLK", "ABCDGIJK":"CJBDAGIK", "ABCDGIJL":"CJBDAGLI", "ABCDGIKL":"IGBCADLK",
    "ABCDGJKL":"CJBDAGLK", "ABCDHIJK":"HJBCADIK", "ABCDHIJL":"HJBCADLI", "ABCDHIKL":"HIBCADLK",
    "ABCDHJKL":"HJBCADLK", "ABCDIJKL":"IJBCADLK", "ABCEFGHI":"HGBCAFEI", "ABCEFGHJ":"HGBCAFEJ",
    "ABCEFGHK":"HGBCAFEK", "ABCEFGHL":"HGBCAFLE", "ABCEFGIJ":"EGBCAFIJ", "ABCEFGIK":"EGBCAFIK",
    "ABCEFGIL":"EGBCAFLI", "ABCEFGJK":"EGBCAFJK", "ABCEFGJL":"EGBCAFLJ", "ABCEFGKL":"EGBCAFLK",
    "ABCEFHIJ":"HJBCAFEI", "ABCEFHIK":"HEBCAFIK", "ABCEFHIL":"HEBCAFLI", "ABCEFHJK":"HJBCAFEK",
    "ABCEFHJL":"HJBCAFLE", "ABCEFHKL":"HEBCAFLK", "ABCEFIJK":"EJBCAFIK", "ABCEFIJL":"EJBCAFLI",
    "ABCEFIKL":"EIBCAFLK", "ABCEFJKL":"EJBCAFLK", "ABCEGHIJ":"HJBCAGEI", "ABCEGHIK":"EGBCAHIK",
    "ABCEGHIL":"EGBCAHLI", "ABCEGHJK":"HJBCAGEK", "ABCEGHJL":"HJBCAGLE", "ABCEGHKL":"EGBCAHLK",
    "ABCEGIJK":"EJBCAGIK", "ABCEGIJL":"EJBCAGLI", "ABCEGIKL":"EGBAICLK", "ABCEGJKL":"EJBCAGLK",
    "ABCEHIJK":"EJBCAHIK", "ABCEHIJL":"EJBCAHLI", "ABCEHIKL":"EIBCAHLK", "ABCEHJKL":"EJBCAHLK",
    "ABCEIJKL":"EJBAICLK", "ABCFGHIJ":"HGBCAFIJ", "ABCFGHIK":"HGBCAFIK", "ABCFGHIL":"HGBCAFLI",
    "ABCFGHJK":"HGBCAFJK", "ABCFGHJL":"HGBCAFLJ", "ABCFGHKL":"HGBCAFLK", "ABCFGIJK":"CJBFAGIK",
    "ABCFGIJL":"CJBFAGLI", "ABCFGIKL":"IGBCAFLK", "ABCFGJKL":"CJBFAGLK", "ABCFHIJK":"HJBCAFIK",
    "ABCFHIJL":"HJBCAFLI", "ABCFHIKL":"HIBCAFLK", "ABCFHJKL":"HJBCAFLK", "ABCFIJKL":"IJBCAFLK",
    "ABCGHIJK":"HJBCAGIK", "ABCGHIJL":"HJBCAGLI", "ABCGHIKL":"IGBCAHLK", "ABCGHJKL":"HJBCAGLK",
    "ABCGIJKL":"IJBCAGLK", "ABCHIJKL":"IJBCAHLK", "ABDEFGHI":"HGBDAFEI", "ABDEFGHJ":"HGBDAFEJ",
    "ABDEFGHK":"HGBDAFEK", "ABDEFGHL":"HGBDAFLE", "ABDEFGIJ":"EGBDAFIJ", "ABDEFGIK":"EGBDAFIK",
    "ABDEFGIL":"EGBDAFLI", "ABDEFGJK":"EGBDAFJK", "ABDEFGJL":"EGBDAFLJ", "ABDEFGKL":"EGBDAFLK",
    "ABDEFHIJ":"HJBDAFEI", "ABDEFHIK":"HEBDAFIK", "ABDEFHIL":"HEBDAFLI", "ABDEFHJK":"HJBDAFEK",
    "ABDEFHJL":"HJBDAFLE", "ABDEFHKL":"HEBDAFLK", "ABDEFIJK":"EJBDAFIK", "ABDEFIJL":"EJBDAFLI",
    "ABDEFIKL":"EIBDAFLK", "ABDEFJKL":"EJBDAFLK", "ABDEGHIJ":"HJBDAGEI", "ABDEGHIK":"EGBDAHIK",
    "ABDEGHIL":"EGBDAHLI", "ABDEGHJK":"HJBDAGEK", "ABDEGHJL":"HJBDAGLE", "ABDEGHKL":"EGBDAHLK",
    "ABDEGIJK":"EJBDAGIK", "ABDEGIJL":"EJBDAGLI", "ABDEGIKL":"EGBAIDLK", "ABDEGJKL":"EJBDAGLK",
    "ABDEHIJK":"EJBDAHIK", "ABDEHIJL":"EJBDAHLI", "ABDEHIKL":"EIBDAHLK", "ABDEHJKL":"EJBDAHLK",
    "ABDEIJKL":"EJBAIDLK", "ABDFGHIJ":"HGBDAFIJ", "ABDFGHIK":"HGBDAFIK", "ABDFGHIL":"HGBDAFLI",
    "ABDFGHJK":"HGBDAFJK", "ABDFGHJL":"HGBDAFLJ", "ABDFGHKL":"HGBDAFLK", "ABDFGIJK":"FJBDAGIK",
    "ABDFGIJL":"FJBDAGLI", "ABDFGIKL":"IGBDAFLK", "ABDFGJKL":"FJBDAGLK", "ABDFHIJK":"HJBDAFIK",
    "ABDFHIJL":"HJBDAFLI", "ABDFHIKL":"HIBDAFLK", "ABDFHJKL":"HJBDAFLK", "ABDFIJKL":"IJBDAFLK",
    "ABDGHIJK":"HJBDAGIK", "ABDGHIJL":"HJBDAGLI", "ABDGHIKL":"IGBDAHLK", "ABDGHJKL":"HJBDAGLK",
    "ABDGIJKL":"IJBDAGLK", "ABDHIJKL":"IJBDAHLK", "ABEFGHIJ":"HJBFAGEI", "ABEFGHIK":"EGBFAHIK",
    "ABEFGHIL":"EGBFAHLI", "ABEFGHJK":"HJBFAGEK", "ABEFGHJL":"HJBFAGLE", "ABEFGHKL":"EGBFAHLK",
    "ABEFGIJK":"EJBFAGIK", "ABEFGIJL":"EJBFAGLI", "ABEFGIKL":"EGBAIFLK", "ABEFGJKL":"EJBFAGLK",
    "ABEFHIJK":"EJBFAHIK", "ABEFHIJL":"EJBFAHLI", "ABEFHIKL":"EIBFAHLK", "ABEFHJKL":"EJBFAHLK",
    "ABEFIJKL":"EJBAIFLK", "ABEGHIJK":"EJBAHGIK", "ABEGHIJL":"EJBAHGLI", "ABEGHIKL":"EGBAIHLK",
    "ABEGHJKL":"EJBAHGLK", "ABEGIJKL":"EJBAIGLK", "ABEHIJKL":"EJBAIHLK", "ABFGHIJK":"HJBFAGIK",
    "ABFGHIJL":"HJBFAGLI", "ABFGHIKL":"HGBAIFLK", "ABFGHJKL":"HJBFAGLK", "ABFGIJKL":"IJBFAGLK",
    "ABFHIJKL":"HJBAIFLK", "ABGHIJKL":"HJBAIGLK", "ACDEFGHI":"HGECAFDI", "ACDEFGHJ":"HGJCAFDE",
    "ACDEFGHK":"HGECAFDK", "ACDEFGHL":"HGFCADLE", "ACDEFGIJ":"CGJDAFEI", "ACDEFGIK":"CGEDAFIK",
    "ACDEFGIL":"CGEDAFLI", "ACDEFGJK":"CGJDAFEK", "ACDEFGJL":"CGJDAFLE", "ACDEFGKL":"CGEDAFLK",
    "ACDEFHIJ":"HJECAFDI", "ACDEFHIK":"HEFCADIK", "ACDEFHIL":"HEFCADLI", "ACDEFHJK":"HJECAFDK",
    "ACDEFHJL":"HJFCADLE", "ACDEFHKL":"HEFCADLK", "ACDEFIJK":"CJEDAFIK", "ACDEFIJL":"CJEDAFLI",
    "ACDEFIKL":"CEIDAFLK", "ACDEFJKL":"CJEDAFLK", "ACDEGHIJ":"HGJCADEI", "ACDEGHIK":"HGECADIK",
    "ACDEGHIL":"HGECADLI", "ACDEGHJK":"HGJCADEK", "ACDEGHJL":"HGJCADLE", "ACDEGHKL":"HGECADLK",
    "ACDEGIJK":"EGJCADIK", "ACDEGIJL":"EGJCADLI", "ACDEGIKL":"EGICADLK", "ACDEGJKL":"EGJCADLK",
    "ACDEHIJK":"HJECADIK", "ACDEHIJL":"HJECADLI", "ACDEHIKL":"HEICADLK", "ACDEHJKL":"HJECADLK",
    "ACDEIJKL":"EJICADLK", "ACDFGHIJ":"HGJCAFDI", "ACDFGHIK":"HGFCADIK", "ACDFGHIL":"HGFCADLI",
    "ACDFGHJK":"HGJCAFDK", "ACDFGHJL":"CGJDAFLH", "ACDFGHKL":"HGFCADLK", "ACDFGIJK":"CGJDAFIK",
    "ACDFGIJL":"CGJDAFLI", "ACDFGIKL":"CGIDAFLK", "ACDFGJKL":"CGJDAFLK", "ACDFHIJK":"HJFCADIK",
    "ACDFHIJL":"HJFCADLI", "ACDFHIKL":"HFICADLK", "ACDFHJKL":"HJFCADLK", "ACDFIJKL":"CJIDAFLK",
    "ACDGHIJK":"HGJCADIK", "ACDGHIJL":"HGJCADLI", "ACDGHIKL":"HGICADLK", "ACDGHJKL":"HGJCADLK",
    "ACDGIJKL":"IGJCADLK", "ACDHIJKL":"HJICADLK", "ACEFGHIJ":"HGJCAFEI", "ACEFGHIK":"HGECAFIK",
    "ACEFGHIL":"HGECAFLI", "ACEFGHJK":"HGJCAFEK", "ACEFGHJL":"HGJCAFLE", "ACEFGHKL":"HGECAFLK",
    "ACEFGIJK":"EGJCAFIK", "ACEFGIJL":"EGJCAFLI", "ACEFGIKL":"EGICAFLK", "ACEFGJKL":"EGJCAFLK",
    "ACEFHIJK":"HJECAFIK", "ACEFHIJL":"HJECAFLI", "ACEFHIKL":"HEICAFLK", "ACEFHJKL":"HJECAFLK",
    "ACEFIJKL":"EJICAFLK", "ACEGHIJK":"EGJCAHIK", "ACEGHIJL":"EGJCAHLI", "ACEGHIKL":"EGICAHLK",
    "ACEGHJKL":"EGJCAHLK", "ACEGIJKL":"EJICAGLK", "ACEHIJKL":"EJICAHLK", "ACFGHIJK":"HGJCAFIK",
    "ACFGHIJL":"HGJCAFLI", "ACFGHIKL":"HGICAFLK", "ACFGHJKL":"HGJCAFLK", "ACFGIJKL":"IGJCAFLK",
    "ACFHIJKL":"HJICAFLK", "ACGHIJKL":"HJICAGLK", "ADEFGHIJ":"HGJDAFEI", "ADEFGHIK":"HGEDAFIK",
    "ADEFGHIL":"HGEDAFLI", "ADEFGHJK":"HGJDAFEK", "ADEFGHJL":"HGJDAFLE", "ADEFGHKL":"HGEDAFLK",
    "ADEFGIJK":"EGJDAFIK", "ADEFGIJL":"EGJDAFLI", "ADEFGIKL":"EGIDAFLK", "ADEFGJKL":"EGJDAFLK",
    "ADEFHIJK":"HJEDAFIK", "ADEFHIJL":"HJEDAFLI", "ADEFHIKL":"HEIDAFLK", "ADEFHJKL":"HJEDAFLK",
    "ADEFIJKL":"EJIDAFLK", "ADEGHIJK":"EGJDAHIK", "ADEGHIJL":"EGJDAHLI", "ADEGHIKL":"EGIDAHLK",
    "ADEGHJKL":"EGJDAHLK", "ADEGIJKL":"EJIDAGLK", "ADEHIJKL":"EJIDAHLK", "ADFGHIJK":"HGJDAFIK",
    "ADFGHIJL":"HGJDAFLI", "ADFGHIKL":"HGIDAFLK", "ADFGHJKL":"HGJDAFLK", "ADFGIJKL":"IGJDAFLK",
    "ADFHIJKL":"HJIDAFLK", "ADGHIJKL":"HJIDAGLK", "AEFGHIJK":"EGJFAHIK", "AEFGHIJL":"EGJFAHLI",
    "AEFGHIKL":"EGIFAHLK", "AEFGHJKL":"EGJFAHLK", "AEFGIJKL":"EJIFAGLK", "AEFHIJKL":"EJIFAHLK",
    "AEGHIJKL":"EJIAHGLK", "AFGHIJKL":"HJIFAGLK", "BCDEFGHI":"CGBDHFEI", "BCDEFGHJ":"HGBCJFDE",
    "BCDEFGHK":"CGBDHFEK", "BCDEFGHL":"CGBDHFLE", "BCDEFGIJ":"CGBDJFEI", "BCDEFGIK":"CGBDEFIK",
    "BCDEFGIL":"CGBDEFLI", "BCDEFGJK":"CGBDJFEK", "BCDEFGJL":"CGBDJFLE", "BCDEFGKL":"CGBDEFLK",
    "BCDEFHIJ":"CJBDHFEI", "BCDEFHIK":"CEBDHFIK", "BCDEFHIL":"CEBDHFLI", "BCDEFHJK":"CJBDHFEK",
    "BCDEFHJL":"CJBDHFLE", "BCDEFHKL":"CEBDHFLK", "BCDEFIJK":"CJBDEFIK", "BCDEFIJL":"CJBDEFLI",
    "BCDEFIKL":"CEBDIFLK", "BCDEFJKL":"CJBDEFLK", "BCDEGHIJ":"HGBCJDEI", "BCDEGHIK":"EGBCHDIK",
    "BCDEGHIL":"EGBCHDLI", "BCDEGHJK":"HGBCJDEK", "BCDEGHJL":"HGBCJDLE", "BCDEGHKL":"EGBCHDLK",
    "BCDEGIJK":"EGBCJDIK", "BCDEGIJL":"EGBCJDLI", "BCDEGIKL":"EGBCIDLK", "BCDEGJKL":"EGBCJDLK",
    "BCDEHIJK":"EJBCHDIK", "BCDEHIJL":"EJBCHDLI", "BCDEHIKL":"EIBCHDLK", "BCDEHJKL":"EJBCHDLK",
    "BCDEIJKL":"EJBCIDLK", "BCDFGHIJ":"HGBCJFDI", "BCDFGHIK":"CGBDHFIK", "BCDFGHIL":"CGBDHFLI",
    "BCDFGHJK":"HGBCJFDK", "BCDFGHJL":"CGBDHFLJ", "BCDFGHKL":"CGBDHFLK", "BCDFGIJK":"CGBDJFIK",
    "BCDFGIJL":"CGBDJFLI", "BCDFGIKL":"CGBDIFLK", "BCDFGJKL":"CGBDJFLK", "BCDFHIJK":"CJBDHFIK",
    "BCDFHIJL":"CJBDHFLI", "BCDFHIKL":"CIBDHFLK", "BCDFHJKL":"CJBDHFLK", "BCDFIJKL":"CJBDIFLK",
    "BCDGHIJK":"HGBCJDIK", "BCDGHIJL":"HGBCJDLI", "BCDGHIKL":"HGBCIDLK", "BCDGHJKL":"HGBCJDLK",
    "BCDGIJKL":"IGBCJDLK", "BCDHIJKL":"HJBCIDLK", "BCEFGHIJ":"HGBCJFEI", "BCEFGHIK":"EGBCHFIK",
    "BCEFGHIL":"EGBCHFLI", "BCEFGHJK":"HGBCJFEK", "BCEFGHJL":"HGBCJFLE", "BCEFGHKL":"EGBCHFLK",
    "BCEFGIJK":"EGBCJFIK", "BCEFGIJL":"EGBCJFLI", "BCEFGIKL":"EGBCIFLK", "BCEFGJKL":"EGBCJFLK",
    "BCEFHIJK":"EJBCHFIK", "BCEFHIJL":"EJBCHFLI", "BCEFHIKL":"EIBCHFLK", "BCEFHJKL":"EJBCHFLK",
    "BCEFIJKL":"EJBCIFLK", "BCEGHIJK":"EJBCHGIK", "BCEGHIJL":"EJBCHGLI", "BCEGHIKL":"EGBCIHLK",
    "BCEGHJKL":"EJBCHGLK", "BCEGIJKL":"EJBCIGLK", "BCEHIJKL":"EJBCIHLK", "BCFGHIJK":"HGBCJFIK",
    "BCFGHIJL":"HGBCJFLI", "BCFGHIKL":"HGBCIFLK", "BCFGHJKL":"HGBCJFLK", "BCFGIJKL":"IGBCJFLK",
    "BCFHIJKL":"HJBCIFLK", "BCGHIJKL":"HJBCIGLK", "BDEFGHIJ":"HGBDJFEI", "BDEFGHIK":"EGBDHFIK",
    "BDEFGHIL":"EGBDHFLI", "BDEFGHJK":"HGBDJFEK", "BDEFGHJL":"HGBDJFLE", "BDEFGHKL":"EGBDHFLK",
    "BDEFGIJK":"EGBDJFIK", "BDEFGIJL":"EGBDJFLI", "BDEFGIKL":"EGBDIFLK", "BDEFGJKL":"EGBDJFLK",
    "BDEFHIJK":"EJBDHFIK", "BDEFHIJL":"EJBDHFLI", "BDEFHIKL":"EIBDHFLK", "BDEFHJKL":"EJBDHFLK",
    "BDEFIJKL":"EJBDIFLK", "BDEGHIJK":"EJBDHGIK", "BDEGHIJL":"EJBDHGLI", "BDEGHIKL":"EGBDIHLK",
    "BDEGHJKL":"EJBDHGLK", "BDEGIJKL":"EJBDIGLK", "BDEHIJKL":"EJBDIHLK", "BDFGHIJK":"HGBDJFIK",
    "BDFGHIJL":"HGBDJFLI", "BDFGHIKL":"HGBDIFLK", "BDFGHJKL":"HGBDJFLK", "BDFGIJKL":"IGBDJFLK",
    "BDFHIJKL":"HJBDIFLK", "BDGHIJKL":"HJBDIGLK", "BEFGHIJK":"EJBFHGIK", "BEFGHIJL":"EJBFHGLI",
    "BEFGHIKL":"EGBFIHLK", "BEFGHJKL":"EJBFHGLK", "BEFGIJKL":"EJBFIGLK", "BEFHIJKL":"EJBFIHLK",
    "BEGHIJKL":"EJIBHGLK", "BFGHIJKL":"HJBFIGLK", "CDEFGHIJ":"CGJDHFEI", "CDEFGHIK":"CGEDHFIK",
    "CDEFGHIL":"CGEDHFLI", "CDEFGHJK":"CGJDHFEK", "CDEFGHJL":"CGJDHFLE", "CDEFGHKL":"CGEDHFLK",
    "CDEFGIJK":"CGEDJFIK", "CDEFGIJL":"CGEDJFLI", "CDEFGIKL":"CGEDIFLK", "CDEFGJKL":"CGEDJFLK",
    "CDEFHIJK":"CJEDHFIK", "CDEFHIJL":"CJEDHFLI", "CDEFHIKL":"CEIDHFLK", "CDEFHJKL":"CJEDHFLK",
    "CDEFIJKL":"CJEDIFLK", "CDEGHIJK":"EGJCHDIK", "CDEGHIJL":"EGJCHDLI", "CDEGHIKL":"EGICHDLK",
    "CDEGHJKL":"EGJCHDLK", "CDEGIJKL":"EGICJDLK", "CDEHIJKL":"EJICHDLK", "CDFGHIJK":"CGJDHFIK",
    "CDFGHIJL":"CGJDHFLI", "CDFGHIKL":"CGIDHFLK", "CDFGHJKL":"CGJDHFLK", "CDFGIJKL":"CGIDJFLK",
    "CDFHIJKL":"CJIDHFLK", "CDGHIJKL":"HGICJDLK", "CEFGHIJK":"EGJCHFIK", "CEFGHIJL":"EGJCHFLI",
    "CEFGHIKL":"EGICHFLK", "CEFGHJKL":"EGJCHFLK", "CEFGIJKL":"EGICJFLK", "CEFHIJKL":"EJICHFLK",
    "CEGHIJKL":"EJICHGLK", "CFGHIJKL":"HGICJFLK", "DEFGHIJK":"EGJDHFIK", "DEFGHIJL":"EGJDHFLI",
    "DEFGHIKL":"EGIDHFLK", "DEFGHJKL":"EGJDHFLK", "DEFGIJKL":"EGIDJFLK", "DEFHIJKL":"EJIDHFLK",
    "DEGHIJKL":"EJIDHGLK", "DFGHIJKL":"HGIDJFLK", "EFGHIJKL":"EJIFHGLK",
}


THIRD_PLACE_ALL_GROUPS = set("ABCDEFGHIJKL")


def _third_dominates(a, b):
    # True only when third-place stats `a` definitely outrank `b` (strict on pts→gd→gf).
    # All equal → a tie we cannot break here, so not a definite ordering.
    if a[1] != b[1]:
        return a[1] > b[1]
    if a[2] != b[2]:
        return a[2] > b[2]
    if a[3] != b[3]:
        return a[3] > b[3]
    return False


def determined_third_slots(finished_thirds: dict) -> dict:
    """Resolve the R32 third-place slots that are ALREADY decided — even before every
    group is final. `finished_thirds` is {group_letter: (team_id, pts, gd, gf)} for the
    groups whose third-placed team is settled. Enumerate every Annex C combination still
    achievable: a not-yet-final group is a wildcard that can finish anywhere (so it never
    rules a combination out), and a combination is impossible only when a settled excluded
    third strictly outranks a settled included one. A winner slot resolves when ALL
    achievable combinations agree on its opponent and that opponent's group is settled.
    Returns {winner_group_letter: third_place_team_id}."""
    achievable = []
    for key in THIRD_PLACE_TABLE:
        groups = set(key)
        ok = True
        for g_in in groups:
            if g_in not in finished_thirds:
                continue
            for g_out in THIRD_PLACE_ALL_GROUPS - groups:
                if g_out in finished_thirds and _third_dominates(finished_thirds[g_out], finished_thirds[g_in]):
                    ok = False
                    break
            if not ok:
                break
        if ok:
            achievable.append(key)
    if not achievable:
        return {}
    result = {}
    for i, win in enumerate(THIRD_PLACE_WINNER_ORDER):
        groups_for_slot = {THIRD_PLACE_TABLE[k][i] for k in achievable}
        if len(groups_for_slot) == 1:
            grp = next(iter(groups_for_slot))
            if grp in finished_thirds:
                result[win] = finished_thirds[grp][0]
    return result


async def resolve_bracket(session: AsyncSession) -> int:
    """Fill knockout match team FKs from their `*_team_label` slots as results land.

    Resolves: "Winner Group X" / "Runner-up Group X" (from a fully-finished group's
    ranked standings) and "Winner Match N" / "Loser Match N" (from finished match N).
    Best-thirds slots ("3rd Group A/B/C/D…") are completed in the live_tracker phase.
    Only fills currently-NULL FKs (idempotent). Returns the number of slots filled.
    Caller commits."""
    # Group winners / runners-up / thirds, only for groups whose matches are all finished.
    group_first: dict[str, int] = {}
    group_second: dict[str, int] = {}
    group_third: dict[str, tuple] = {}
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
        if len(ranked) >= 3:
            t3 = ranked[2]
            group_third[letter] = (t3.team_id, t3.pts or 0, t3.gd or 0, t3.gf or 0)

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

    # Thirds → R32 winner slots (Annex C). Resolves each slot the moment it's decided
    # across every still-possible qualifying combination, so a winner-vs-third match can
    # fill in before the last group is final; a "3rd Group …" slot's occupant is keyed off
    # the OTHER side's "Winner Group X" label.
    third_by_winner = determined_third_slots(group_third)

    def resolve_third_label(side_label, other_label):
        if not side_label or not side_label.strip().lower().startswith("3rd group"):
            return None
        ol = (other_label or "").strip()
        if not ol.lower().startswith("winner group "):
            return None
        return third_by_winner.get(ol[-1].upper())

    def _mutable(m: "WCMatch") -> bool:
        # A slot's participants may still change while the knockout match has not been
        # played. Unplayed fixtures carry placeholder 0-0 scores (not NULL), so treat a
        # falsy (NULL or 0) score as "no result"; a real live score (non-zero) or a
        # finished match freezes the slot. This lets a late group-result correction
        # reflow here while played games never move.
        return (not m.finished) and not m.home_score and not m.away_score

    filled = 0
    for m in ko:
        mutable = _mutable(m)
        new_home = resolve_label(m.home_team_label) or resolve_match_label(m.home_team_label)
        if new_home and new_home != m.home_team_id and (m.home_team_id is None or mutable):
            m.home_team_id = new_home
            filled += 1
        new_away = resolve_label(m.away_team_label) or resolve_match_label(m.away_team_label)
        if new_away and new_away != m.away_team_id and (m.away_team_id is None or mutable):
            m.away_team_id = new_away
            filled += 1

    if filled:
        await session.flush()
    return filled
