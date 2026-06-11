"""
ai_player — Developer (L6) endpoints to drive the AI quiniela player.

A developer browses a day's matches and triggers a per-match AI analysis. The grounded
web search runs in the bot (only its Gemini provider supports grounding), so the trigger
records the request in ``ai_match_analysis`` (status=queued) and enqueues the match id on
Redis; the bot fills in the analysis + decision and fans the pick out to every guild's
leaderboard. The dashboard polls the analysis endpoint to show the full analysis and the
final scoreline. All endpoints require platform admin (Level 6 — Developer).
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.redis import get_redis
from app.api.deps import verify_platform_admin

router = APIRouter()

CDMX = timezone(timedelta(hours=-6))
REQUEST_KEY = "ai_player:requests"

_MATCHES_SQL = text("""
    SELECT m.id AS id, ht.name_en AS home, at.name_en AS away,
           extract(epoch from m.kickoff_at)::bigint AS kickoff_unix,
           m.finished AS finished, m.type AS round, m."group" AS grp,
           a.status AS status, a.pred_home AS pred_home, a.pred_away AS pred_away
    FROM matches m
    LEFT JOIN teams ht ON ht.id = m.home_team_id
    LEFT JOIN teams at ON at.id = m.away_team_id
    LEFT JOIN ai_match_analysis a ON a.match_id = m.id
    WHERE m.kickoff_at >= :start AND m.kickoff_at < :end
    ORDER BY m.kickoff_at, m.id
""")


def _cdmx_day_window(day: str):
    """[start, end) UTC bounds for a CDMX calendar day 'YYYY-MM-DD'."""
    try:
        y, mo, d = (int(x) for x in day.split("-"))
        start = datetime(y, mo, d, tzinfo=CDMX)
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid day; use YYYY-MM-DD")
    return start, start + timedelta(days=1)


@router.get("/ai-player/matches")
async def list_matches(
    day: str,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(verify_platform_admin),
):
    """Matches on a CDMX day, with each one's AI-analysis status/decision (for the dev UI)."""
    start, end = _cdmx_day_window(day)
    rows = (await db.execute(_MATCHES_SQL, {"start": start, "end": end})).mappings().all()
    return {"day": day, "matches": [dict(r) for r in rows]}


@router.post("/ai-player/analyze/{match_id}")
async def analyze_match(
    match_id: int,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(verify_platform_admin),
    redis=Depends(get_redis),
):
    """Queue a match for AI analysis (the bot does the grounded search)."""
    m = (await db.execute(
        text("SELECT id, finished, home_team_id, away_team_id FROM matches WHERE id = :mid"),
        {"mid": match_id},
    )).mappings().first()
    if not m:
        raise HTTPException(status_code=404, detail="Partido no encontrado")
    if m["finished"]:
        raise HTTPException(status_code=409, detail="El partido ya terminó")
    if m["home_team_id"] is None or m["away_team_id"] is None:
        raise HTTPException(status_code=409, detail="Los equipos aún no están definidos")

    await db.execute(text("""
        INSERT INTO ai_match_analysis (match_id, status, requested_by, updated_at)
        VALUES (:mid, 'queued', :uid, now())
        ON CONFLICT (match_id)
        DO UPDATE SET status = 'queued', requested_by = :uid, updated_at = now()
    """), {"mid": match_id, "uid": int(admin["user_id"])})
    await db.commit()
    await redis.rpush(REQUEST_KEY, str(match_id))
    return {"match_id": match_id, "status": "queued"}


@router.get("/ai-player/analysis/{match_id}")
async def get_analysis(
    match_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(verify_platform_admin),
):
    """The stored AI analysis + final decision for a match (UI polls this)."""
    row = (await db.execute(text("""
        SELECT match_id, status, analysis, pred_home, pred_away, confidence, updated_at
        FROM ai_match_analysis WHERE match_id = :mid
    """), {"mid": match_id})).mappings().first()
    if not row:
        return {"match_id": match_id, "status": "none"}
    return dict(row)


@router.get("/ai-player/public/analysis/{match_id}")
async def public_analysis(match_id: int, db: AsyncSession = Depends(get_db)):
    """Public (no auth): the AI's full written analysis attached to a match, so anyone
    viewing the game can read it. Returns the complete analysis text once it's finished
    ('done')."""
    row = (await db.execute(text("""
        SELECT match_id, status, analysis, updated_at
        FROM ai_match_analysis WHERE match_id = :mid AND status = 'done'
    """), {"mid": match_id})).mappings().first()
    if not row or not row["analysis"]:
        return {"match_id": match_id, "status": "none"}
    return {
        "match_id": row["match_id"],
        "status": "done",
        "analysis": row["analysis"],
        "updated_at": row["updated_at"],
    }
