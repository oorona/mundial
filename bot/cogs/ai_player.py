"""
ai_player — the machine "player" in the quiniela, triggered per-match from the UI.

A Developer (L6) opens a match in the dashboard and presses "Analyze". The backend
can't do Google Search grounding (only the bot's Gemini provider can), so it records the
request in ``ai_match_analysis`` (status=queued) and pushes the match id onto the Redis
list ``ai_player:requests``. This cog polls that list and, per match:

  1. reads the web consensus (odds, previews, pundit forecasts) via grounded Gemini —
     the full analysis text is kept for display,
  2. parses a final scoreline (the "decision"),
  3. stores analysis + decision in ``ai_match_analysis`` (global, shown in the UI),
  4. fans the pick out as a Prediction by a special AI user ("🤖 IA") to EVERY guild
     that runs the quiniela, so the AI competes against humans on every server's board.

Picks are scored by the live_tracker engine like any player's. A match already analyzed
is reused (no re-query). Runs on the RLS-bypassed worker session (the bot is the only
writer).
"""
import json
import logging

from discord.ext import commands, tasks
from sqlalchemy import text

log = logging.getLogger("ai_player")

# Reserved sentinel id for the machine player. Real Discord IDs are 17-19 digit
# snowflakes, so a small constant never collides with a human; Prediction.user_id has
# no FK, so no users row is required.
AI_USER_ID = 1
DEFAULT_AI_NAME = "🤖 IA"
REQUEST_KEY = "ai_player:requests"

PREDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "home_goals": {"type": "integer"},
        "away_goals": {"type": "integer"},
        "confidence": {"type": "number"},
    },
    "required": ["home_goals", "away_goals"],
}

# Registered in the editable llm_schemas store (LLM Configs → Schemas) so admins can
# see/edit the AI player's structured output. The cog seeds it on load and loads it at
# run time; the inline PREDICT_SCHEMA above is the guarded fallback (used if the row is
# missing or an edit dropped a required key).
PREDICT_SCHEMA_ID = "ai_player_predict"
PREDICT_SCHEMA_DOC = {
    "id": PREDICT_SCHEMA_ID,
    "name": "AI Player — match prediction",
    "description": (
        "Structured output the AI player extracts from its grounded web analysis: the "
        "predicted scoreline (home_goals, away_goals) and confidence. Stored on "
        "ai_match_analysis and fanned to every guild's leaderboard."
    ),
    "schema": PREDICT_SCHEMA,
}

_MATCH_SQL = text("""
    SELECT m.id AS id, ht.name_en AS home, at.name_en AS away, m.finished AS finished,
           to_char(m.kickoff_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS day
    FROM matches m
    JOIN teams ht ON ht.id = m.home_team_id
    JOIN teams at ON at.id = m.away_team_id
    WHERE m.id = :mid
""")
_POOLS_SQL = text("SELECT guild_id FROM prediction_pools")


class AIPlayer(commands.Cog):
    """Machine player; analyzes a match from internet consensus on demand (L6-triggered)."""

    SETTINGS_SCHEMA = {
        "id": "ai_player",
        "label": "aiPlayer.settings.label",
        "description": "aiPlayer.settings.desc",
        "fields": [
            {"key": "ai_player_enabled", "type": "boolean", "label": "aiPlayer.settings.enabled", "default": True},
            {"key": "ai_player_name", "type": "text", "label": "aiPlayer.settings.name", "default": DEFAULT_AI_NAME},
        ],
    }

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.services.db
        self.llm = getattr(bot.services, "llm", None)
        self.redis = getattr(bot.services, "redis", None)
        self.poll_loop.start()

    def cog_unload(self):
        self.poll_loop.cancel()

    @tasks.loop(seconds=8)
    async def poll_loop(self):
        """Drain UI-triggered analysis requests (one match id per list entry)."""
        if not self.db or not self.llm or not self.redis:
            return
        provider = self.llm.providers.get("google") if self.llm.providers else None
        if provider is None:
            return
        for _ in range(10):  # bounded drain per tick
            try:
                raw = await self.redis.lpop(REQUEST_KEY)
            except Exception:
                return
            if not raw:
                return
            try:
                match_id = int(raw)
            except (TypeError, ValueError):
                continue
            await self._process(provider, match_id)

    @poll_loop.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()
        await self._seed_schema()

    async def _seed_schema(self):
        """Register the predict schema in llm_schemas so it shows in LLM Configs.

        Idempotent (ON CONFLICT DO NOTHING) — never clobbers a dashboard edit. The
        llm_schemas table is a global framework table; written RLS-bypassed.
        """
        try:
            async with self.db.worker_session() as s:
                await s.execute(text("""
                    INSERT INTO llm_schemas (id, name, description, body)
                    VALUES (:id, :name, :desc, CAST(:body AS json))
                    ON CONFLICT (id) DO NOTHING
                """), {
                    "id": PREDICT_SCHEMA_DOC["id"], "name": PREDICT_SCHEMA_DOC["name"],
                    "desc": PREDICT_SCHEMA_DOC["description"], "body": json.dumps(PREDICT_SCHEMA_DOC),
                })
                await s.commit()
        except Exception as e:
            log.warning("ai_player: schema seed failed: %r", e)

    async def _predict_schema(self) -> dict:
        """Load the editable predict schema from llm_schemas; inline fallback if the row
        is missing or an edit dropped a required key (home_goals/away_goals)."""
        try:
            async with self.db.worker_session() as s:
                body = (await s.execute(
                    text("SELECT body FROM llm_schemas WHERE id = :id"), {"id": PREDICT_SCHEMA_ID}
                )).scalar()
            if isinstance(body, str):
                body = json.loads(body)
            if isinstance(body, dict):
                sch = body.get("schema", body)
                props = sch.get("properties", {}) if isinstance(sch, dict) else {}
                if isinstance(sch, dict) and "home_goals" in props and "away_goals" in props:
                    return sch
        except Exception as e:
            log.warning("ai_player: schema load failed, using inline: %r", e)
        return PREDICT_SCHEMA

    @staticmethod
    def _parse(settings_json) -> dict:
        if isinstance(settings_json, str):
            try:
                return json.loads(settings_json) or {}
            except Exception:
                return {}
        return dict(settings_json or {})

    async def _set_status(self, match_id, status, analysis=None, home=None, away=None, conf=None):
        async with self.db.worker_session() as s:
            await s.execute(text("""
                UPDATE ai_match_analysis
                SET status = :st,
                    analysis = COALESCE(:an, analysis),
                    pred_home = COALESCE(:h, pred_home),
                    pred_away = COALESCE(:a, pred_away),
                    confidence = COALESCE(:c, confidence),
                    updated_at = now()
                WHERE match_id = :mid
            """), {"st": status, "an": analysis, "h": home, "a": away, "c": conf, "mid": match_id})
            await s.commit()

    async def _process(self, provider, match_id):
        async with self.db.worker_session() as s:
            row = (await s.execute(_MATCH_SQL, {"mid": match_id})).mappings().first()
        if not row or row["finished"]:
            await self._set_status(match_id, "error")
            return
        await self._set_status(match_id, "running")

        result = await self._analyze(provider, row)
        if result is None:
            await self._set_status(match_id, "error")
            return
        analysis, h, a, conf = result
        await self._set_status(match_id, "done", analysis=analysis, home=h, away=a, conf=conf)

        # Fan the decision out to every guild that runs the quiniela.
        async with self.db.worker_session() as s:
            pool_guilds = [r[0] for r in (await s.execute(_POOLS_SQL)).all()]
            settings_rows = (await s.execute(text("SELECT guild_id, settings_json FROM guild_settings"))).all()
        names = {g: (self._parse(j).get("ai_player_name") or DEFAULT_AI_NAME) for g, j in settings_rows}
        for g in pool_guilds:
            await self._save(g, match_id, names.get(g, DEFAULT_AI_NAME), h, a)
        log.info("ai_player: analyzed match %s → %s-%s, fanned out to %d guild(s)",
                 match_id, h, a, len(pool_guilds))

    async def _analyze(self, provider, m) -> tuple[str, int, int, float | None] | None:
        """Grounded web analysis → (analysis_text, home, away, confidence)."""
        try:
            from services.llm import LLMMessage
            sys = self.llm.load_prompt("ai_player", "predict_fetch", "system_prompt") or (
                "Eres un analista de fútbol. Usa la búsqueda web para revisar pronósticos, "
                "cuotas de apuestas y análisis de expertos sobre un partido del Mundial 2026. "
                "Explica brevemente el contexto (forma, bajas, favoritismo) y concluye con el "
                "marcador EXACTO más probable según el consenso. Responde en español (es-MX)."
            )
            tmpl = self.llm.load_prompt("ai_player", "predict_fetch", "user_prompt") or (
                "Partido del Mundial 2026: {home} vs {away} (fecha {day}). "
                "Analiza y di el marcador final más probable según pronósticos y cuotas en internet."
            )
            user = tmpl.format(home=m["home"], away=m["away"], day=m.get("day", ""))
            grounded = await provider.generate_response(
                [LLMMessage(role="user", content=user)],
                system_prompt=sys,
                tools=[{"google_search": {}}],
            )
            analysis = grounded if isinstance(grounded, str) else json.dumps(grounded)

            parse_sys = self.llm.load_prompt("ai_player", "predict_parse", "system_prompt") or (
                "Extrae un objeto JSON estricto con el marcador pronosticado (home_goals, away_goals, "
                "confidence 0-1) del texto. Usa enteros para los goles."
            )
            parse_tmpl = self.llm.load_prompt("ai_player", "predict_parse", "user_prompt") or "{text}"
            schema = await self._predict_schema()
            data = await self.llm.generate_structured(
                parse_tmpl.format(text=analysis), schema, system_prompt=parse_sys
            )
            if isinstance(data, dict) and "home_goals" in data and "away_goals" in data:
                h, a = int(data["home_goals"]), int(data["away_goals"])
                conf = data.get("confidence")
                conf = float(conf) if isinstance(conf, (int, float)) else None
                if 0 <= h <= 20 and 0 <= a <= 20:
                    return analysis, h, a, conf
        except Exception as e:
            log.warning("ai_player: analyze failed for match %s: %r", m.get("id"), e)
        return None

    async def _save(self, guild_id, match_id, name, h, a):
        async with self.db.worker_session() as s:
            await s.execute(text("""
                INSERT INTO predictions (guild_id, user_id, username, match_id, pred_home, pred_away, points)
                VALUES (:gid, :aid, :name, :mid, :h, :a, 0)
                ON CONFLICT (guild_id, user_id, match_id)
                DO UPDATE SET pred_home = EXCLUDED.pred_home, pred_away = EXCLUDED.pred_away,
                              username = EXCLUDED.username
            """), {"gid": guild_id, "aid": AI_USER_ID, "name": name, "mid": match_id, "h": h, "a": a})
            await s.commit()


async def setup(bot):
    await bot.add_cog(AIPlayer(bot))
