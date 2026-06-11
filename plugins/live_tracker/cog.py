"""
live_tracker — AI worker cog.

During live windows it polls in-progress matches, uses Gemini with Google Search
grounding to read the current/final score (two-call pipeline: grounded text → strict
JSON), auto-commits confident finals, then recomputes group standings, resolves the
bracket and re-scores predictions — all via raw SQL on the RLS-bypassed worker session
(the bot process has no backend ORM). Live events are streamed to a Discord channel and
to the web via a Redis stream. Admin corrections (backend override endpoint) are picked
up automatically because recompute/rescore run every tick over all finished matches.
"""
import json
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import text

log = logging.getLogger("live_tracker")

DEFAULT_ACCENT = "#ef4444"

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "description": "notstarted|live|halftime|finished|penalties"},
        "home_score": {"type": "integer"},
        "away_score": {"type": "integer"},
        "minute": {"type": "string"},
        "home_pens": {"type": "integer"},
        "away_pens": {"type": "integer"},
        "finished": {"type": "boolean"},
        "confidence": {"type": "number"},
        "events": {
            "type": "array",
            "description": "Key match events in chronological order: goals (with scorer), "
                           "cards, substitutions, penalty-shootout kicks, VAR decisions.",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description":
                             "goal|own_goal|penalty_goal|penalty_miss|yellow|red|"
                             "second_yellow|substitution|var"},
                    "team": {"type": "string", "description": "'home' or 'away'"},
                    "minute": {"type": "string", "description": "e.g. \"23'\", \"45+2'\", \"HT\""},
                    "player": {"type": "string", "description": "player involved (scorer / booked / sent off / coming on)"},
                    "detail": {"type": "string", "description": "extra info: assist, player going off in a sub, card reason"},
                },
                "required": ["type"],
            },
        },
    },
    "required": ["status", "home_score", "away_score", "finished", "confidence"],
}

# Registered in the editable llm_schemas store (LLM Configs → Schemas). Seeded on load,
# loaded at run time; SCORE_SCHEMA above is the guarded fallback (used if the row is
# missing or an edit dropped home_score/away_score).
SCORE_SCHEMA_ID = "live_tracker_score"
SCORE_SCHEMA_DOC = {
    "id": SCORE_SCHEMA_ID,
    "name": "Live Tracker — match score",
    "description": (
        "Structured output the live tracker extracts from grounded web search: current "
        "status, home/away score, minute, penalties, finished flag, confidence, and a full "
        "events timeline (goals + scorer, yellow/red cards, substitutions, shootout kicks, VAR)."
    ),
    "schema": SCORE_SCHEMA,
}

_INWINDOW_SQL = text("""
    SELECT m.id AS id, m.type AS round_code,
           ht.name_en AS home_name, at.name_en AS away_name
    FROM matches m
    JOIN teams ht ON ht.id = m.home_team_id
    JOIN teams at ON at.id = m.away_team_id
    WHERE m.finished = false
      AND m.kickoff_at IS NOT NULL
      AND m.kickoff_at <= now() + interval '5 minutes'
      AND m.kickoff_at >= now() - interval '3 hours'
""")


class LiveTracker(commands.Cog):
    """AI live-score worker: polls in-progress matches, commits confident finals, recomputes standings/bracket, re-scores predictions, and streams live events to Discord + the web."""

    SETTINGS_SCHEMA = {
        "id": "live_tracker",
        "label": "liveTracker.settings.label",
        "description": "liveTracker.settings.desc",
        "fields": [
            {"key": "lt_enabled", "type": "boolean", "label": "liveTracker.settings.enabled", "default": False},
            {"key": "lt_channel_id", "type": "channel_select", "label": "liveTracker.settings.channel", "default": None},
            {"key": "lt_notify_role_id", "type": "role_select", "label": "liveTracker.settings.notifyRole", "default": None},
            {"key": "lt_goal_channel_id", "type": "channel_select", "label": "liveTracker.settings.goalChannel", "default": None},
            {"key": "lt_goal_role_id", "type": "role_select", "label": "liveTracker.settings.goalRole", "default": None},
            # NOTE: result auto-commit + its confidence threshold are intentionally NOT
            # per-guild settings. Committing a final result writes the GLOBAL matches table,
            # so it affects every server's scoring and the shared AI player — a platform
            # (developer) concern, not something an individual owner should change. The
            # commit logic lives in _apply() with a fixed threshold; tune it there.
            {"key": "lt_accent", "type": "color", "label": "liveTracker.settings.accent", "default": DEFAULT_ACCENT},
        ],
    }

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.services.db
        self.llm = bot.services.llm
        self.redis = getattr(bot.services, "redis", None)
        self._last_status: dict[int, str] = {}
        self._live_msg: dict[tuple[int, int], int] = {}   # (guild_id, match_id) -> message id
        self._threads: dict[tuple[int, str], int] = {}    # (guild_id, field) -> thread id; field = match id or "inaug"
        self._last_feed: dict[int, str] = {}
        self._seen_events: dict[int, set[str]] = {}   # match_id -> set of event keys (feed dedup)
        self.tick.start()

    def cog_unload(self):
        self.tick.cancel()

    @tasks.loop(seconds=120)
    async def tick(self):
        if not self.db:
            return
        provider = self.llm.providers.get("google") if (self.llm and self.llm.providers) else None
        inwindow = await self._read_inwindow()
        if inwindow:
            # ── LIVE mode (every 2 min during a game window): AI score + events ──
            ai: dict[int, dict] = {}
            for m in inwindow:
                r = await self._ai_for_match(provider, m) if provider else None
                if r:
                    ai[m["id"]] = r
            async with self.db.worker_session() as s:
                await self._apply(s, inwindow, ai)
                await self._recompute_standings(s)
                await self._resolve_bracket(s)
                await self._rescore(s)
                settings_rows = (await s.execute(text("SELECT guild_id, settings_json FROM guild_settings"))).all()
                snapshot = await self._live_snapshot(s)
                await s.commit()
            await self._broadcast(settings_rows, snapshot, ai)
            new_goals = await self._publish_live_events(snapshot, ai)
            await self._announce_goals(settings_rows, new_goals)
        else:
            # ── NEWS mode (every 8h when nothing is live): AI news about the next/
            # inauguration match → channel + app feed. Confirms the AI pipeline.
            # The inauguration is not a match, so it refreshes slowly (8h); a real
            # match in window switches to LIVE mode above (2-min cadence). ──
            await self._maybe_news(provider)

    @tick.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()
        await self._seed_schema()

    async def _seed_schema(self):
        """Register the score schema in llm_schemas so it shows in LLM Configs.

        Insert if absent; if a stale pre-events default is stored (its schema has no
        ``events`` property), upgrade it in place. A row that already carries an events
        timeline — an admin edit, or an already-upgraded default — is left untouched.
        """
        try:
            async with self.db.worker_session() as s:
                await s.execute(text("""
                    INSERT INTO llm_schemas (id, name, description, body)
                    VALUES (:id, :name, :desc, CAST(:body AS json))
                    ON CONFLICT (id) DO UPDATE
                    SET name = EXCLUDED.name, description = EXCLUDED.description,
                        body = EXCLUDED.body, updated_at = now()
                    WHERE (llm_schemas.body #> '{schema,properties,events}') IS NULL
                """), {
                    "id": SCORE_SCHEMA_DOC["id"], "name": SCORE_SCHEMA_DOC["name"],
                    "desc": SCORE_SCHEMA_DOC["description"], "body": json.dumps(SCORE_SCHEMA_DOC),
                })
                await s.commit()
        except Exception as e:
            log.warning("live_tracker: schema seed failed: %r", e)

    async def _score_schema(self) -> dict:
        """Load the editable score schema from llm_schemas; inline fallback if the row is
        missing or an edit dropped a required key (home_score/away_score)."""
        try:
            async with self.db.worker_session() as s:
                body = (await s.execute(
                    text("SELECT body FROM llm_schemas WHERE id = :id"), {"id": SCORE_SCHEMA_ID}
                )).scalar()
            if isinstance(body, str):
                body = json.loads(body)
            if isinstance(body, dict):
                sch = body.get("schema", body)
                props = sch.get("properties", {}) if isinstance(sch, dict) else {}
                if isinstance(sch, dict) and "home_score" in props and "away_score" in props:
                    return sch
        except Exception as e:
            log.warning("live_tracker: schema load failed, using inline: %r", e)
        return SCORE_SCHEMA

    # ── Global AI feed (app "Now" tab via SSE) + hourly pre-tournament news ──────
    NEWS_INTERVAL = 12 * 3600

    async def _push_event(self, ev: dict):
        if not self.redis:
            return
        data = json.dumps(ev)
        try:
            await self.redis.xadd("live:events", {"data": data})
            await self.redis.lpush("live:events:recent", data)
            await self.redis.ltrim("live:events:recent", 0, 49)
        except Exception:
            pass

    async def _publish_live_events(self, snapshot, ai: dict[int, dict] | None = None) -> list[dict]:
        """Streams feed updates; returns the NEW goal events seen this tick (already
        deduped via _seen_events) so the tick can announce them to goal channels."""
        ai = ai or {}
        new_goals: list[dict] = []
        for m in snapshot:
            score = f"{m['hs']}–{m['as_']}" if m["hs"] is not None else "vs"
            state = "FT" if m["finished"] else (m["te"] or "EN JUEGO")
            line = f"{m['home']} {score} {m['away']} · {state}"
            if self._last_feed.get(m["id"]) != line:
                self._last_feed[m["id"]] = line
                await self._push_event({"type": "live", "match_id": m["id"], "home": m["home"], "away": m["away"],
                                        "home_score": m["hs"], "away_score": m["as_"], "state": state,
                                        "text": line, "ts": int(time.time())})

            # Granular events (goals/cards/subs/…): announce each only once.
            r = ai.get(m["id"]) or {}
            seen = self._seen_events.setdefault(m["id"], set())
            for ev in (r.get("events") or []):
                if not isinstance(ev, dict):
                    continue
                etype = _norm_event_type(ev.get("type"))
                if not etype:
                    continue
                player = str(ev.get("player") or "").strip()
                minute = str(ev.get("minute") or "").strip()
                key = f"{etype}|{minute.lower()}|{str(ev.get('team') or '').lower()}|{player.lower()}"
                if key in seen:
                    continue
                seen.add(key)
                text = _fmt_event(ev, etype, m["home"], m["away"])
                await self._push_event({"type": etype, "match_id": m["id"], "home": m["home"],
                                        "away": m["away"], "player": player, "minute": minute,
                                        "text": text, "ts": int(time.time())})
                if etype in ("goal", "own_goal", "penalty_goal"):
                    new_goals.append({"home": m["home"], "away": m["away"], "ev": ev, "etype": etype})
        return new_goals

    # The gif-bot user pinged after every confirmed goal announcement.
    GOAL_GIF_USER_ID = 1355258979789312100

    async def _announce_goals(self, settings_rows, goals: list[dict]):
        """Confirmed-goal pings: for each goal event seen for the FIRST time this tick,
        post '¡GOOOL de X contra Y!' to the guild's goal channel (lt_goal_channel_id),
        then ask the gif bot for a goal gif. Dedup lives in _publish_live_events, so a
        goal is announced at most once per bot process."""
        if not goals:
            return
        for guild_id, settings_json in settings_rows:
            settings = settings_json if isinstance(settings_json, dict) else _safe_json(settings_json)
            if not settings.get("lt_enabled") or not settings.get("lt_goal_channel_id"):
                continue
            guild = self.bot.get_guild(int(guild_id))
            channel = guild.get_channel(int(settings["lt_goal_channel_id"])) if guild else None
            if channel is None:
                continue
            # Goal-ping role: separate from lt_notify_role_id (which tags the stream
            # thread on match start) so servers can have a dedicated "goals" role.
            goal_role_id = settings.get("lt_goal_role_id")
            ping = f"<@&{int(goal_role_id)}> " if goal_role_id else ""
            for g in goals:
                home, away, ev = g["home"], g["away"], g["ev"]
                scorer = _team_name(ev, home, away)
                if g["etype"] == "own_goal":
                    # an own goal counts FOR the opposing side
                    scorer = away if scorer == home else home if scorer == away else scorer
                other = away if scorer == home else home
                player = str(ev.get("player") or "").strip()
                minute = str(ev.get("minute") or "").strip()
                detail = f" — {player}" if player else ""
                if minute:
                    detail += f" ({minute}')" if minute[:1].isdigit() and not minute.endswith("'") else f" ({minute})"
                try:
                    await channel.send(
                        f"{ping}⚽ ¡GOOOL de **{scorer or home}** contra **{other}**!{detail}",
                        allowed_mentions=discord.AllowedMentions(roles=True),
                    )
                    # Include the scoring team (and player/minute when known) so each
                    # gif request is a distinct message, not a repeated identical line.
                    await channel.send(
                        f"<@{self.GOAL_GIF_USER_ID}> goal of {scorer or home}{detail} — find a goal gif",
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
                except discord.HTTPException as e:
                    log.warning("live_tracker: goal announce failed (guild %s): %r", guild_id, e)

    async def _next_match(self) -> dict | None:
        async with self.db.worker_session() as s:
            row = (await s.execute(text("""
                SELECT m.id AS id, ht.name_en AS home, at.name_en AS away
                FROM matches m JOIN teams ht ON ht.id = m.home_team_id JOIN teams at ON at.id = m.away_team_id
                WHERE m.finished = false AND m.kickoff_at IS NOT NULL
                ORDER BY m.kickoff_at LIMIT 1
            """))).mappings().first()
        return dict(row) if row else None

    async def _ai_news(self, provider, m: dict) -> str | None:
        if not provider:
            return None
        try:
            from services.llm import LLMMessage
            sys = self.llm.load_prompt("live_tracker", "news_fetch", "system_prompt") or (
                "Eres un reportero del Mundial 2026. En 2-3 frases resume una noticia reciente y real sobre la "
                "INAUGURACIÓN del torneo: la ceremonia de apertura, la sede inaugural (Estadio Azteca, Ciudad de "
                "México), el ambiente y los preparativos del primer día. Usa la búsqueda. No inventes. "
                "Responde ÚNICAMENTE en español (es-MX): si las fuentes están en inglés, tradúcelas; "
                "no escribas nada en inglés.")
            tmpl = self.llm.load_prompt("live_tracker", "news_fetch", "user_prompt") or (
                "Noticia reciente sobre la inauguración del Mundial 2026 (ceremonia de apertura y día inaugural "
                "en el Estadio Azteca de Ciudad de México). Recuerda responder en español.")
            user = tmpl.format(home=m["home"], away=m["away"])
            txt = await provider.generate_response(
                [LLMMessage(role="user", content=user)], system_prompt=sys, tools=[{"google_search": {}}])
            txt = txt if isinstance(txt, str) else json.dumps(txt)
            txt = txt.strip()
            # Discord embed descriptions cap at 4096 chars — keep headroom. If the
            # article must be cut, cut at the end of a sentence, never mid-word.
            if len(txt) > 4000:
                cut = txt[:4000]
                for sep in (". ", "! ", "? ", "\n"):
                    i = cut.rfind(sep)
                    if i > 2000:
                        cut = cut[: i + 1]
                        break
                else:
                    cut = cut[: cut.rfind(" ")] + "…"
                txt = cut.rstrip()
            return txt or None
        except Exception:
            return None

    async def _tournament_started(self) -> bool:
        """True once any match has finished — i.e. the tournament is underway. The
        inauguration stream is a PRE-tournament exception; once a real match has been
        played the feed is only about live games, never the inauguration."""
        async with self.db.worker_session() as s:
            n = (await s.execute(text("SELECT count(*) FROM matches WHERE finished = true"))).scalar()
        return bool(n)

    async def _maybe_news(self, provider):
        if not self.redis or not provider:
            return
        # Inauguration news is the pre-tournament exception only. Once the tournament
        # has started, no news mode — the stream is about live games.
        if await self._tournament_started():
            return
        try:
            last = await self.redis.get("live:news:last_ts")
        except Exception:
            last = None
        now = time.time()
        if last is not None:
            try:
                if now - float(last) < self.NEWS_INTERVAL:
                    return
            except Exception:
                pass
        nm = await self._next_match()
        if not nm:
            return
        news = await self._ai_news(provider, nm)
        if not news:
            return
        try:
            await self.redis.set("live:news:last_ts", now)
            # Inauguration is not a match: keep its card to a single fresh item rather
            # than a growing pile of hourly posts. Clear the shared feed before posting
            # the 8h update; LIVE mode (every 2 min) repopulates it once a game is in
            # window, so real matches — including the opener — keep their rolling feed.
            await self.redis.delete("live:events", "live:events:recent")
        except Exception:
            pass
        await self._push_event({"type": "news", "match_id": nm["id"], "home": nm["home"],
                                "away": nm["away"], "text": news, "ts": int(now)})
        async with self.db.worker_session() as s:
            rows = (await s.execute(text("SELECT guild_id, settings_json FROM guild_settings"))).all()
        log.info("live_tracker: news ready, scanning %d guild_settings row(s)", len(rows))
        for guild_id, settings_json in rows:
            settings = settings_json if isinstance(settings_json, dict) else _safe_json(settings_json)
            if not settings.get("lt_enabled") or not settings.get("lt_channel_id"):
                log.info("live_tracker: skip guild %s (lt_enabled=%r, lt_channel_id=%r)",
                         guild_id, settings.get("lt_enabled"), settings.get("lt_channel_id"))
                continue
            guild = self.bot.get_guild(int(guild_id))
            channel = guild.get_channel(int(settings["lt_channel_id"])) if guild else None
            if channel is None:
                log.warning("live_tracker: guild %s channel %s not resolvable (guild_cached=%s) — "
                            "check the bot can see that channel", guild_id, settings.get("lt_channel_id"),
                            guild is not None)
                continue
            thread = await self._news_thread(channel, guild_id)
            target = thread or channel
            embed = discord.Embed(
                title="🎉 Inauguración · Mundial 2026",
                description=news, color=_color(settings.get("lt_accent") or DEFAULT_ACCENT))
            embed.set_footer(text="Mundial 2026 · noticias (IA)")
            try:
                await target.send(embed=embed)
                log.info("live_tracker: posted news to %s (guild %s) via %s",
                         getattr(target, "id", "?"), guild_id,
                         "thread" if thread is not None else "channel")
            except discord.HTTPException as e:
                log.warning("live_tracker: failed to post news (guild %s): %r", guild_id, e)

    # Slash command (/envivo) intentionally removed — live matches are followed in the
    # Discord Activity now. The tick worker above still streams the live feed/embeds.
    # Only the framework's /status command remains bot-side.

    # ── AI pipeline ────────────────────────────────────────────────────────────
    async def _read_inwindow(self) -> list[dict]:
        async with self.db.worker_session() as s:
            rows = (await s.execute(_INWINDOW_SQL)).mappings().all()
        return [dict(r) for r in rows]

    async def _ai_for_match(self, provider, m: dict) -> dict | None:
        try:
            from services.llm import LLMMessage
            sys = self.llm.load_prompt("live_tracker", "score_fetch", "system_prompt") or (
                "Eres un asistente que sigue EN VIVO un partido del Mundial 2026 usando la búsqueda en internet. "
                "Informa el marcador y el estado ACTUALES y, además, TODOS los eventos clave del partido en orden "
                "cronológico: goles (con el minuto y el goleador, indica autogol o gol de penal), tarjetas amarillas "
                "y rojas (jugador y minuto), sustituciones (quién entra y quién sale, minuto), tanda de penales y "
                "decisiones del VAR. Sé conservador si no estás seguro y no inventes. "
                "Responde ÚNICAMENTE en español (es-MX); si las fuentes están en inglés, tradúcelas."
            )
            tmpl = self.llm.load_prompt("live_tracker", "score_fetch", "user_prompt") or (
                "Partido: {home} vs {away}. Dame el marcador y el estado actuales, y la lista completa de eventos "
                "(goles con goleador y minuto, tarjetas, cambios, penales, VAR)."
            )
            user = tmpl.format(home=m["home_name"], away=m["away_name"])
            grounded = await provider.generate_response(
                [LLMMessage(role="user", content=user)],
                system_prompt=sys,
                tools=[{"google_search": {}}],
            )
            grounded = grounded if isinstance(grounded, str) else json.dumps(grounded)

            parse_sys = self.llm.load_prompt("live_tracker", "score_parse", "system_prompt") or (
                "Extrae un objeto JSON estricto del texto, incluido el arreglo 'events' con cada gol, "
                "tarjeta, cambio, penal y VAR (type, team='home'/'away', minute, player, detail). "
                "Si no estás seguro, baja la confianza."
            )
            parse_tmpl = self.llm.load_prompt("live_tracker", "score_parse", "user_prompt") or "{text}"
            schema = await self._score_schema()
            data = await self.llm.generate_structured(
                parse_tmpl.format(text=grounded), schema, system_prompt=parse_sys
            )
            if isinstance(data, dict) and "home_score" in data and "away_score" in data:
                return data
        except Exception:
            return None
        return None

    async def _commit_config(self, s) -> tuple[bool, float]:
        """Global result auto-commit config (set by Developers on the Live Tracker card,
        stored in app_config). Committing a final writes the shared matches table, so it's
        platform-wide, not per-guild. Defaults: enabled, confidence ≥ 0.8."""
        try:
            rows = (await s.execute(text(
                "SELECT key, value FROM app_config WHERE key IN ('lt_auto_commit','lt_commit_confidence')"
            ))).all()
            cfg = {k: v for k, v in rows}
            enabled = cfg.get("lt_auto_commit", "true") != "false"
            conf = float(cfg.get("lt_commit_confidence", "0.8"))
        except Exception:
            return True, 0.8
        return enabled, conf

    async def _apply(self, s, inwindow: list[dict], ai: dict[int, dict]):
        # Commit a final only when finished & confident enough. The auto-commit toggle and
        # confidence threshold are a GLOBAL developer setting (app_config). Idempotent
        # (finished=false guard).
        auto_commit, threshold = await self._commit_config(s)
        for m in inwindow:
            r = ai.get(m["id"])
            if not r:
                continue
            if auto_commit and r.get("finished") and float(r.get("confidence", 0)) >= threshold:
                await s.execute(
                    text("""
                        UPDATE matches
                        SET home_score = :hs, away_score = :as_, finished = true,
                            home_pens = :hp, away_pens = :ap, time_elapsed = 'FT'
                        WHERE id = :id AND finished = false
                    """),
                    {"hs": int(r["home_score"]), "as_": int(r["away_score"]),
                     "hp": r.get("home_pens"), "ap": r.get("away_pens"), "id": m["id"]},
                )
            else:
                await s.execute(
                    text("UPDATE matches SET time_elapsed = :te WHERE id = :id AND finished = false"),
                    {"te": str(r.get("minute") or r.get("status") or "")[:20], "id": m["id"]},
                )

    # ── Recompute standings ──────────────────────────────────────────────────────
    async def _recompute_standings(self, s):
        matches = (await s.execute(text("""
            SELECT "group" AS grp, home_team_id, away_team_id, home_score, away_score
            FROM matches
            WHERE type = 'group' AND finished = true
              AND home_score IS NOT NULL AND away_score IS NOT NULL
              AND home_team_id IS NOT NULL AND away_team_id IS NOT NULL
        """))).mappings().all()
        tally: dict[int, dict] = {}

        def row(tid):
            return tally.setdefault(tid, dict(mp=0, w=0, d=0, l=0, gf=0, ga=0))

        for m in matches:
            h, a = row(m["home_team_id"]), row(m["away_team_id"])
            h["mp"] += 1; a["mp"] += 1
            h["gf"] += m["home_score"]; h["ga"] += m["away_score"]
            a["gf"] += m["away_score"]; a["ga"] += m["home_score"]
            if m["home_score"] > m["away_score"]:
                h["w"] += 1; a["l"] += 1
            elif m["home_score"] < m["away_score"]:
                a["w"] += 1; h["l"] += 1
            else:
                h["d"] += 1; a["d"] += 1

        standings = (await s.execute(text('SELECT team_id, "group" AS grp FROM group_standings'))).mappings().all()
        for st in standings:
            t = tally.get(st["team_id"], dict(mp=0, w=0, d=0, l=0, gf=0, ga=0))
            await s.execute(
                text("""UPDATE group_standings
                        SET mp=:mp, w=:w, d=:d, l=:l, gf=:gf, ga=:ga, gd=:gd, pts=:pts
                        WHERE team_id=:tid AND "group"=:g"""),
                {"mp": t["mp"], "w": t["w"], "d": t["d"], "l": t["l"], "gf": t["gf"], "ga": t["ga"],
                 "gd": t["gf"] - t["ga"], "pts": t["w"] * 3 + t["d"], "tid": st["team_id"], "g": st["grp"]},
            )

    # ── Resolve bracket (winners/runners + match winner/loser) ───────────────────
    async def _resolve_bracket(self, s):
        # group winners/runners for fully-finished groups
        first, second = {}, {}
        for letter in [chr(c) for c in range(ord("A"), ord("L") + 1)]:
            gm = (await s.execute(
                text("SELECT finished FROM matches WHERE type='group' AND \"group\"=:g"), {"g": letter}
            )).scalars().all()
            if not gm or not all(gm):
                continue
            ranked = (await s.execute(
                text('SELECT team_id FROM group_standings WHERE "group"=:g ORDER BY pts DESC, gd DESC, gf DESC'),
                {"g": letter},
            )).scalars().all()
            if len(ranked) >= 2:
                first[letter], second[letter] = ranked[0], ranked[1]

        ko = (await s.execute(text("""
            SELECT id, home_team_id, away_team_id, home_team_label, away_team_label,
                   home_score, away_score, home_pens, away_pens, finished
            FROM matches WHERE type <> 'group'
        """))).mappings().all()
        by_id = {m["id"]: m for m in ko}

        def winner_loser(m):
            if not m or not m["finished"] or m["home_team_id"] is None or m["away_team_id"] is None:
                return (None, None)
            hs, as_ = m["home_score"], m["away_score"]
            if hs is None or as_ is None:
                return (None, None)
            if hs > as_:
                return (m["home_team_id"], m["away_team_id"])
            if as_ > hs:
                return (m["away_team_id"], m["home_team_id"])
            hp, ap = m["home_pens"], m["away_pens"]
            if hp is not None and ap is not None and hp != ap:
                return (m["home_team_id"], m["away_team_id"]) if hp > ap else (m["away_team_id"], m["home_team_id"])
            return (None, None)

        def resolve(label):
            if not label:
                return None
            low = label.strip().lower()
            if low.startswith("winner group "):
                return first.get(label.strip()[-1].upper())
            if low.startswith("runner-up group ") or low.startswith("runner up group "):
                return second.get(label.strip()[-1].upper())
            if low.startswith("winner match ") or low.startswith("loser match "):
                digits = "".join(ch for ch in label if ch.isdigit())
                if not digits:
                    return None
                src = by_id.get(int(digits))
                win, lose = winner_loser(src)
                return win if low.startswith("winner") else lose
            return None

        for m in ko:
            if m["home_team_id"] is None:
                tid = resolve(m["home_team_label"])
                if tid:
                    await s.execute(text("UPDATE matches SET home_team_id=:t WHERE id=:i AND home_team_id IS NULL"), {"t": tid, "i": m["id"]})
            if m["away_team_id"] is None:
                tid = resolve(m["away_team_label"])
                if tid:
                    await s.execute(text("UPDATE matches SET away_team_id=:t WHERE id=:i AND away_team_id IS NULL"), {"t": tid, "i": m["id"]})

    # ── Rescore predictions (all guilds) ─────────────────────────────────────────
    async def _rescore(self, s):
        rows = (await s.execute(text("""
            SELECT p.id AS id, p.pred_home AS ph, p.pred_away AS pa,
                   m.home_score AS hs, m.away_score AS as_, m.type AS round_code,
                   COALESCE(pool.weight_exact, 4) AS we,
                   COALESCE(pool.weight_diff, 3) AS wd,
                   COALESCE(pool.weight_tendency, 2) AS wt,
                   COALESCE(pool.knockout_multiplier, 2) AS km
            FROM predictions p
            JOIN matches m ON m.id = p.match_id
            LEFT JOIN prediction_pools pool ON pool.guild_id = p.guild_id
            WHERE m.finished = true AND m.home_score IS NOT NULL AND m.away_score IS NOT NULL
        """))).mappings().all()
        for r in rows:
            pts = _score(r["ph"], r["pa"], r["hs"], r["as_"], r["we"], r["wd"], r["wt"], r["km"], r["round_code"] != "group")
            await s.execute(
                text("UPDATE predictions SET points=:p, scored_at=now() WHERE id=:i AND points IS DISTINCT FROM :p"),
                {"p": pts, "i": r["id"]},
            )

    # ── Live snapshot + streaming ────────────────────────────────────────────────
    async def _live_snapshot(self, s) -> list[dict]:
        rows = (await s.execute(text("""
            SELECT m.id AS id, ht.name_en AS home, at.name_en AS away,
                   m.home_score AS hs, m.away_score AS as_, m.finished AS finished,
                   m.time_elapsed AS te, m.home_pens AS hp, m.away_pens AS ap
            FROM matches m
            JOIN teams ht ON ht.id = m.home_team_id
            JOIN teams at ON at.id = m.away_team_id
            WHERE m.kickoff_at IS NOT NULL
              AND m.kickoff_at <= now() + interval '5 minutes'
              AND m.kickoff_at >= now() - interval '3 hours'
            ORDER BY m.kickoff_at
        """))).mappings().all()
        return [dict(r) for r in rows]

    def _live_embed(self, snapshot: list[dict], accent_hex: str) -> discord.Embed:
        embed = discord.Embed(title="🔴 En vivo — Mundial 2026", color=_color(accent_hex))
        if not snapshot:
            embed.description = "No hay partidos en vivo ahora mismo."
            return embed
        for m in snapshot:
            score = f"{m['hs']}–{m['as_']}" if m["hs"] is not None else "vs"
            state = "FINAL" if m["finished"] else (m["te"] or "EN JUEGO")
            embed.add_field(name=f"{m['home']} {score} {m['away']}", value=state, inline=False)
        return embed

    async def _broadcast(self, settings_rows, snapshot, ai):
        for guild_id, settings_json in settings_rows:
            settings = settings_json if isinstance(settings_json, dict) else _safe_json(settings_json)
            if not settings.get("lt_enabled") or not settings.get("lt_channel_id"):
                continue
            guild = self.bot.get_guild(int(guild_id))
            if guild is None:
                continue
            channel = guild.get_channel(int(settings["lt_channel_id"]))
            if channel is None:
                continue
            accent = settings.get("lt_accent") or DEFAULT_ACCENT
            # one thread per match under the stream channel; the match's whole feed
            # (kickoff, live embed, final) lives in its own thread.
            notify_role_id = settings.get("lt_notify_role_id")
            for m in snapshot:
                thread = await self._match_thread(channel, guild_id, m, notify_role_id)
                if thread is None:
                    continue
                await self._emit_transition(thread, m)
                events = (ai.get(m["id"]) or {}).get("events") if ai else None
                embed = self._match_embed(m, accent, events)
                await self._upsert_match_message(thread, guild_id, m["id"], embed)
            # web SSE
            if self.redis:
                try:
                    await self.redis.xadd(f"live:{guild_id}", {"data": json.dumps({"type": "tick", "matches": len(snapshot)})})
                except Exception:
                    pass

    def _thread_name(self, m) -> str:
        home = m.get("home") or m.get("home_name") or "?"
        away = m.get("away") or m.get("away_name") or "?"
        return f"{home} vs {away}"[:100]

    async def _match_thread(self, channel, guild_id, m, notify_role_id=None):
        """Per-match thread under the stream channel (created when the match goes live).
        Tags ``notify_role_id`` (if configured) the first time a match's thread is created."""
        return await self._get_thread(channel, guild_id, str(m["id"]), self._thread_name(m),
                                      notify_role_id=notify_role_id)

    async def _news_thread(self, channel, guild_id):
        """The dedicated 'Inauguración' thread for pre-tournament AI news — the FIRST thread,
        kept separate from the per-match threads. Once the first match kicks off, the live
        flow creates its own per-match thread (see _broadcast), so the inauguration thread
        stays as the opening announcement."""
        return await self._get_thread(channel, guild_id, "inaug", "🎉 Inauguración · Mundial 2026")

    async def _get_thread(self, channel, guild_id, field: str, name: str, notify_role_id=None):
        """Get-or-create (and unarchive) a public thread under the stream channel.

        Thread ids are cached in memory and mirrored to the Redis hash
        `live:threads:{guild_id}` under `field` (a match id as a string, or "inaug" for the
        inauguration thread) so they survive a bot restart — without that we'd spawn a
        duplicate thread every redeploy.
        """
        key = (int(guild_id), field)
        tid = self._threads.get(key)
        if tid is None and self.redis:
            try:
                v = await self.redis.hget(f"live:threads:{guild_id}", field)
                if v:
                    tid = int(v)
            except Exception:
                tid = None
        if tid:
            thread = (channel.guild.get_thread(tid) if channel.guild else None)
            if thread is None:
                try:
                    thread = await self.bot.fetch_channel(tid)
                except (discord.NotFound, discord.HTTPException):
                    thread = None
            if thread is not None:
                if getattr(thread, "archived", False):
                    try:
                        await thread.edit(archived=False)
                    except discord.HTTPException:
                        pass
                self._threads[key] = thread.id
                return thread
        # create a fresh public thread (channel must be a text/forum channel)
        try:
            thread = await channel.create_thread(
                name=name,
                type=discord.ChannelType.public_thread,
                auto_archive_duration=1440,
            )
        except discord.Forbidden:
            log.warning("live_tracker: missing 'Create Public Threads' in channel %s (guild %s); "
                        "falling back to parent channel", getattr(channel, "id", "?"), guild_id)
            return None
        except (discord.HTTPException, AttributeError, TypeError) as e:
            log.warning("live_tracker: could not create thread in channel %s (guild %s): %r",
                        getattr(channel, "id", "?"), guild_id, e)
            return None
        self._threads[key] = thread.id
        if self.redis:
            try:
                await self.redis.hset(f"live:threads:{guild_id}", field, str(thread.id))
            except Exception:
                pass
        # Tag the configured role the first time this match's thread is created, so members
        # get pinged when a new live-stream thread opens. (Needs the bot to be able to
        # mention the role — either a mentionable role or the 'Mention @everyone, here, and
        # All Roles' permission.)
        if notify_role_id:
            try:
                await thread.send(
                    f"<@&{int(notify_role_id)}> 🔴 ¡Comienza la transmisión en vivo! **{name}**",
                    allowed_mentions=discord.AllowedMentions(roles=True),
                )
            except (discord.HTTPException, ValueError) as e:
                log.warning("live_tracker: could not ping role %s in new thread (guild %s): %r",
                            notify_role_id, guild_id, e)
        return thread

    def _match_embed(self, m, accent_hex: str, events=None) -> discord.Embed:
        score = f"{m['hs']}–{m['as_']}" if m["hs"] is not None else "vs"
        state = "🏁 FINAL" if m["finished"] else f"🔴 {m['te'] or 'EN JUEGO'}"
        embed = discord.Embed(
            title=f"{m['home']} {score} {m['away']}", description=state, color=_color(accent_hex))
        if m.get("hp") is not None and m.get("ap") is not None:
            embed.add_field(name="🥅 Penales", value=f"{m['hp']}–{m['ap']}", inline=True)
        for name, value in _timeline_fields(events, m["home"], m["away"]):
            embed.add_field(name=name, value=value, inline=False)
        embed.set_footer(text="Mundial 2026 · actualización en vivo (IA)")
        return embed

    async def _emit_transition(self, thread, m):
        state = "FT" if m["finished"] else "LIVE"
        prev = self._last_status.get(m["id"])
        if prev == state:
            return
        self._last_status[m["id"]] = state
        try:
            if state == "LIVE" and prev is None:
                await thread.send(f"🟢 **Comienza:** {m['home']} vs {m['away']}")
            elif state == "FT":
                await thread.send(f"🏁 **Final:** {m['home']} {m['hs']}–{m['as_']} {m['away']}")
        except discord.HTTPException:
            pass

    async def _upsert_match_message(self, thread, guild_id, match_id, embed):
        key = (int(guild_id), int(match_id))
        mid = self._live_msg.get(key)
        if mid:
            try:
                msg = await thread.fetch_message(mid)
                await msg.edit(embed=embed)
                return
            except (discord.NotFound, discord.HTTPException):
                pass
        try:
            msg = await thread.send(embed=embed)
            self._live_msg[key] = msg.id
        except discord.HTTPException:
            pass


def _score(ph, pa, ah, aa, we, wd, wt, km, is_ko) -> int:
    # A prediction row exists only if the user participated, and this runs only for
    # finished matches → every scored pick earns a 1-pt participation floor, with
    # correctness added on top (knockout doubles the correctness part only).
    # wrong=1, tendency=1+wt, diff=1+wd, exact=1+we; KO exact=1+(we*km).
    if ph is None or pa is None or ah is None or aa is None:
        return 0  # not scorable yet (match not finished)
    ph, pa, ah, aa = int(ph), int(pa), int(ah), int(aa)
    if ph == ah and pa == aa:
        base = we
    elif (ph - pa) == (ah - aa) and (ah - aa) != 0:
        base = wd
    elif ((ph - pa) > 0) - ((ph - pa) < 0) == ((ah - aa) > 0) - ((ah - aa) < 0):
        base = wt
    else:
        base = 0
    correctness = int(round(base * float(km))) if (base and is_ko) else int(base)
    return 1 + correctness


_EVENT_EMOJI = {
    "goal": "⚽", "own_goal": "🥅", "penalty_goal": "⚽", "penalty_miss": "❌",
    "yellow": "🟨", "red": "🟥", "second_yellow": "🟥", "substitution": "🔄", "var": "📺",
}
_EVENT_ALIASES = {
    "gol": "goal", "owngoal": "own_goal", "autogol": "own_goal", "own": "own_goal",
    "penalty": "penalty_goal", "penal": "penalty_goal", "penalty_scored": "penalty_goal",
    "missed_penalty": "penalty_miss", "penalty_missed": "penalty_miss",
    "yellow_card": "yellow", "amarilla": "yellow", "booking": "yellow",
    "red_card": "red", "roja": "red", "sending_off": "red",
    "double_yellow": "second_yellow", "second_yellow_card": "second_yellow",
    "sub": "substitution", "cambio": "substitution", "substitucion": "substitution",
}


def _norm_event_type(t):
    """Normalize a model-supplied event type to a known key, or None to drop it."""
    t = str(t or "").strip().lower().replace(" ", "_").replace("-", "_")
    t = _EVENT_ALIASES.get(t, t)
    return t if t in _EVENT_EMOJI else None


def _team_name(ev, home, away) -> str:
    side = str(ev.get("team") or "").strip().lower()
    if side in ("home", "local"):
        return home
    if side in ("away", "visitor", "visitante", "away_team"):
        return away
    return str(ev.get("team") or "").strip()  # already a team name, or empty


def _fmt_event(ev, etype, home, away) -> str:
    """One human line for an event, e.g. '⚽ 23' L. Messi (Argentina) — assist: Di María'."""
    emoji = _EVENT_EMOJI.get(etype, "•")
    minute = str(ev.get("minute") or "").strip()
    if minute and minute[:1].isdigit() and not minute.endswith("'"):
        minute = f"{minute}'"
    player = str(ev.get("player") or "").strip()
    detail = str(ev.get("detail") or "").strip()
    team = _team_name(ev, home, away)
    label = player or etype.replace("_", " ")
    line = " ".join(p for p in (emoji, minute, label) if p)
    if team:
        line += f" ({team})"
    if detail and detail.lower() != player.lower():
        line += f" — {detail}"
    return line


def _timeline_fields(events, home, away):
    """Group events into (field_name, value) tuples for the live embed; [] if none."""
    if not events:
        return []
    goals, cards, subs, other = [], [], [], []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        et = _norm_event_type(ev.get("type"))
        if not et:
            continue
        line = _fmt_event(ev, et, home, away)
        if et in ("goal", "own_goal", "penalty_goal", "penalty_miss"):
            goals.append(line)
        elif et in ("yellow", "red", "second_yellow"):
            cards.append(line)
        elif et == "substitution":
            subs.append(line)
        else:
            other.append(line)

    def _block(lines):
        v = "\n".join(lines)
        return (v[:1020] + "\n…") if len(v) > 1024 else v

    fields = []
    if goals:
        fields.append(("⚽ Goles", _block(goals)))
    if cards:
        fields.append(("🟨🟥 Tarjetas", _block(cards)))
    if subs:
        fields.append(("🔄 Cambios", _block(subs)))
    if other:
        fields.append(("📺 Otros", _block(other)))
    return fields


def _color(hex_str: str) -> int:
    try:
        return int(str(hex_str).lstrip("#")[:6], 16)
    except Exception:
        return int(DEFAULT_ACCENT.lstrip("#"), 16)


def _safe_json(v):
    try:
        return json.loads(v) if isinstance(v, str) else (v or {})
    except Exception:
        return {}


async def setup(bot):
    await bot.add_cog(LiveTracker(bot))
