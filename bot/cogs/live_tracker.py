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
import os
import re
import time
import unicodedata

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
# Structured output for vetting + translating a Fox clip in one call (see _caption_for_clip):
# is it a GOAL, WHICH live match it's about (1-based index, 0 = none), and the Spanish caption.
CLIP_RELAY_SCHEMA = {
    "type": "object",
    "properties": {
        "is_goal": {"type": "boolean"},
        "match": {"type": "integer"},
        "es": {"type": "string"},
    },
    "required": ["is_goal", "match", "es"],
}

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
           ht.name_en AS home_name, at.name_en AS away_name,
           m.home_score AS hs, m.away_score AS as_, m.time_elapsed AS te,
           round(extract(epoch FROM (now() - m.kickoff_at)) / 60)::int AS mins_since_ko
    FROM matches m
    JOIN teams ht ON ht.id = m.home_team_id
    JOIN teams at ON at.id = m.away_team_id
    WHERE m.finished = false
      AND m.kickoff_at IS NOT NULL
      AND m.kickoff_at <= now() + interval '5 minutes'
      -- Stop polling a dead game: group matches can't go to extra time, so they
      -- can't run past ~kickoff+2h30m; only knockouts need the 3h tail (ET + pens).
      -- A committed final already leaves the window earlier; this just caps the
      -- worst case (a final that never commits) so it can't burn the full 3h.
      -- The cap MUST stay well above the commit floor below (120') so a legit final
      -- has several ticks to land and confirm before the window closes.
      AND m.kickoff_at >= now() - (CASE WHEN m.type = 'group'
                                        THEN interval '150 minutes'
                                        ELSE interval '3 hours' END)
""")

# Post-match reconcile sweep. A committed final can lock a score moments before a
# 90'+ goal is indexed (the live read settles on a stoppage-time or pre-whistle
# state, then the match leaves the in-window query and is never re-checked). This
# picks finished matches back up ONCE the result has had time to settle and become
# well-indexed — roughly an hour after a group game ends (~kickoff+170') — and
# re-reads the DEFINITIVE final so a missed late goal gets corrected. Capped at 6h
# so old games are never re-polled; a Redis marker makes it fire once per match.
_RECONCILE_SQL = text("""
    SELECT m.id AS id, m.type AS round_code,
           ht.name_en AS home_name, at.name_en AS away_name,
           m.home_score AS hs, m.away_score AS as_,
           m.home_pens AS hp, m.away_pens AS ap
    FROM matches m
    JOIN teams ht ON ht.id = m.home_team_id
    JOIN teams at ON at.id = m.away_team_id
    WHERE m.finished = true
      AND m.kickoff_at IS NOT NULL
      AND m.kickoff_at <= now() - interval '170 minutes'
      AND m.kickoff_at >= now() - interval '6 hours'
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
        self._clip_pump.start()

    def cog_unload(self):
        self.tick.cancel()
        self._clip_pump.cancel()

    @tasks.loop(seconds=300)
    async def tick(self):
        if not self.db:
            return
        provider = self.llm.providers.get("google") if (self.llm and self.llm.providers) else None
        inwindow = await self._read_inwindow()
        if inwindow:
            # ── LIVE mode (every 5 min during a game window): AI score + events ──
            await self._fresh_window_wipe()
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
            # Pushes goal/score events to the WEB feed (Now tab) AND returns the new goals
            # (deduped, budget-capped, minute-ordered). The web stream is the sole goal
            # decision-maker: we announce each new goal to the Discord goal channel here.
            # The Fox X clips post independently via _clip_pump (no coordination).
            new_goals = await self._publish_live_events(snapshot, ai)
            await self._announce_new_goals(settings_rows, new_goals)
        else:
            # ── NEWS mode (every 8h when nothing is live): AI news about the next/
            # inauguration match → channel + app feed. Confirms the AI pipeline.
            # The inauguration is not a match, so it refreshes slowly (8h); a real
            # match in window switches to LIVE mode above (5-min cadence). ──
            if self.redis:
                try:
                    await self.redis.delete("live:window_active")
                except Exception:
                    pass
            await self._maybe_news(provider)
        # Post-match safety sync runs in BOTH modes: a game that finished earlier may
        # still need its final reconciled while a newer game is live (or none is).
        # Isolated so a reconcile hiccup never kills the tick loop.
        try:
            await self._reconcile_finals(provider)
        except Exception as e:
            log.warning("live_tracker: reconcile pass failed: %r", e)

    async def _fresh_window_wipe(self):
        """When a live window OPENS (no game was in window before this tick), clear
        the previous game's feed — the stream now belongs to the new game. The
        Redis marker (not memory) means a mid-game restart never wipes the feed."""
        if not self.redis:
            return
        try:
            fresh = await self.redis.set("live:window_active", "1", nx=True, ex=14400)
            if fresh:
                await self.redis.delete("live:events", "live:events:recent")
            else:
                await self.redis.expire("live:window_active", 14400)
        except Exception:
            pass

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
        deduped via _seen_events) so the tick can announce them to goal channels.

        The feed is a curated narrative, not a status log: one kickoff marker, one
        halftime marker, events (goals capped at the scoreboard), a score line ONLY
        when the score changes, and one final marker pushed LAST so it tops the feed."""
        ai = ai or {}
        new_goals: list[dict] = []
        for m in snapshot:
            score = f"{m['hs']}–{m['as_']}" if m["hs"] is not None else "vs"
            state_raw = str(m["te"] or "").strip().lower().replace(" ", "_")
            underway = state_raw not in ("", "notstarted", "not_started")
            if not m["finished"] and underway and await self._first_time(m["id"], "kickoff"):
                await self._push_event({"type": "kickoff", "match_id": m["id"], "home": m["home"],
                                        "away": m["away"],
                                        "text": f"🏟️ ¡Comienza el partido! {m['home']} vs {m['away']}",
                                        "ts": int(time.time())})
                await self._ctx_add(m["id"], "Comenzó el partido")
            if not m["finished"] and state_raw in ("halftime", "ht", "descanso") \
                    and await self._first_time(m["id"], "halftime"):
                await self._push_event({"type": "halftime", "match_id": m["id"], "home": m["home"],
                                        "away": m["away"],
                                        "text": f"⏸️ Descanso: {m['home']} {score} {m['away']}",
                                        "ts": int(time.time())})
                await self._ctx_add(m["id"], f"Descanso al {score}")

            # Granular events (goals/cards/subs/…): announce each only once. The
            # dedup context is PERSISTED in Redis (live:seen:{match}) so restarts
            # don't re-report, with keys normalized against AI wording wobble.
            r = ai.get(m["id"]) or {}
            seen = self._seen_events.setdefault(m["id"], set())
            # Running scoreline per goal (minute-sorted) so each announcement shows its
            # TRUE score regardless of the order the AI surfaced the goals across polls.
            run = _running_scores(r.get("events"), r.get("status"))
            for ev in (r.get("events") or []):
                if not isinstance(ev, dict):
                    continue
                etype = _norm_event_type(ev.get("type"))
                if not etype:
                    continue
                # If it isn't clear, don't post it: a card/sub with an unknown player
                # is noise ("🟥 unknown desconocido"). Goals are the exception — the
                # score itself is the substance, and the budget cap dedups them.
                if etype not in ("goal", "own_goal", "penalty_goal") and not _known(ev.get("player")):
                    continue
                player = _known(ev.get("player"))
                minute = str(ev.get("minute") or "").strip()
                key = _event_key(ev, etype)
                if key in seen:
                    continue
                if not await self._first_time(m["id"], key):
                    seen.add(key)
                    continue
                seen.add(key)
                if etype in ("goal", "own_goal", "penalty_goal"):
                    # Never report more goals than the scoreboard holds — the AI
                    # re-words old goals (new minute/detail) and they'd slip past
                    # key dedup; the budget blocks them from feed AND channel.
                    if not await self._goal_budget_ok(m["id"], r):
                        continue
                    h, a = run.get(key, (m["hs"] or 0, m["as_"] or 0))
                    new_goals.append({"match_id": m["id"], "home": m["home"], "away": m["away"],
                                      "ev": ev, "etype": etype, "team": ev.get("team"),
                                      "minute": minute, "player": player, "h": h, "a": a})
                text = _fmt_event(ev, etype, m["home"], m["away"])
                await self._push_event({"type": etype, "match_id": m["id"], "home": m["home"],
                                        "away": m["away"], "player": player, "minute": minute,
                                        "text": text, "ts": int(time.time())})
                await self._ctx_add(m["id"], text)

            # Score line ONLY when the score actually changes — minute/status updates
            # are noise (a wobbling status used to spam the feed every tick). The
            # final marker is pushed LAST so it lands newest and tops the feed.
            if m["finished"]:
                if await self._first_time(m["id"], "final"):
                    await self._push_event({"type": "final", "match_id": m["id"], "home": m["home"],
                                            "away": m["away"], "home_score": m["hs"], "away_score": m["as_"],
                                            "text": f"🏁 FINAL — {m['home']} {score} {m['away']}",
                                            "ts": int(time.time())})
                    await self._ctx_add(m["id"], f"FINAL {score}")
            elif m["hs"] is not None and await self._score_changed(m["id"], m["hs"], m["as_"]):
                mn = str(m["te"] or "").strip()
                mn = mn if re.fullmatch(r"\d{1,3}(\+\d{1,2})?'?", mn) else ""
                line = f"{m['home']} {score} {m['away']}" + (f" · {mn}" if mn else "")
                await self._push_event({"type": "live", "match_id": m["id"], "home": m["home"], "away": m["away"],
                                        "home_score": m["hs"], "away_score": m["as_"],
                                        "text": line, "ts": int(time.time())})
        return new_goals

    async def _score_changed(self, match_id: int, hs, as_) -> bool:
        """True only when the score differs from the last one we pushed (Redis-backed
        so restarts don't re-push). The initial 0–0 is not a change — the kickoff
        marker covers the start."""
        cur = f"{hs}-{as_}"
        if self._last_feed.get(match_id) == cur:
            return False
        self._last_feed[match_id] = cur
        prev = None
        if self.redis:
            try:
                prev = _dec(await self.redis.get(f"live:lastscore:{match_id}"))
                await self.redis.set(f"live:lastscore:{match_id}", cur, ex=21600)
            except Exception:
                prev = None
        if prev is not None and prev == cur:
            return False
        return not (prev is None and cur == "0-0")

    async def _final_confirmed(self, match_id: int, hs, as_) -> bool:
        """Debounce AND verify the final: True only when TWO consecutive polls both
        report finished with the SAME score. A flaky or hallucinated final score
        (the cause of wrong committed results) won't repeat identically, so it never
        commits. The marker stores the score and survives restarts via Redis."""
        cur = f"{int(hs)}-{int(as_)}"
        if not self.redis:
            return True
        try:
            prev = _dec(await self.redis.get(f"live:final_pending:{match_id}"))
            await self.redis.set(f"live:final_pending:{match_id}", cur, ex=1800)
            return prev is not None and prev == cur
        except Exception:
            return True

    async def _clear_final_pending(self, match_id: int):
        if not self.redis:
            return
        try:
            await self.redis.delete(f"live:final_pending:{match_id}")
        except Exception:
            pass

    async def _first_time(self, match_id: int, key: str) -> bool:
        """Redis-persisted event dedup (survives restarts); True if never reported."""
        if not self.redis:
            return True
        try:
            rkey = f"live:seen:{match_id}"
            added = await self.redis.sadd(rkey, key)
            await self.redis.expire(rkey, 21600)  # 6h — outlives any match
            return bool(added)
        except Exception:
            return True

    async def _goal_budget_ok(self, match_id: int, r: dict) -> bool:
        """Cap goal announcements at the AI's reported total score (Redis-persisted):
        a goal can only be announced while announced-count < home+away goals."""
        if not self.redis:
            return True
        try:
            total = int(r.get("home_score") or 0) + int(r.get("away_score") or 0)
            rkey = f"live:goals_announced:{match_id}"
            prev = int(await self.redis.get(rkey) or 0)
            if prev >= total:
                return False
            await self.redis.incr(rkey)
            await self.redis.expire(rkey, 21600)
            return True
        except Exception:
            return True

    # ── Goal clips (Fox X) — independent relay, NOT coordinated with the web stream ──
    # The two streams post independently. The WEB stream (grounded search) is the sole
    # goal decision-maker and announces "¡GOOOL!" (see _announce_new_goals). The CLIP
    # stream is a dumb relay: the client captures a Fox video + its English text during
    # the game window and uploads it; here we translate the text to Spanish and post the
    # video with that caption. No classification, no team-matching, no holding/windowing.

    @tasks.loop(seconds=45)
    async def _clip_pump(self):
        """Drain uploaded Fox clips and post each as a video with a Spanish caption."""
        if not self.redis or not self.db:
            return
        try:
            # Peek the queue first so we only pay for settings + window lookups when there's
            # actually a clip to post.
            v = await self.redis.rpop("goal_clips:incoming")
            if v is None:
                return
            live = await self._read_inwindow()  # live matches now (teams used to vet relevance)
            async with self.db.worker_session() as s:
                settings_rows = (await s.execute(
                    text("SELECT guild_id, settings_json FROM guild_settings"))).all()
            for _ in range(50):
                if v is None:
                    break
                try:
                    clip = json.loads(_dec(v))
                except Exception:
                    v = await self.redis.rpop("goal_clips:incoming")
                    continue
                await self._relay_clip(settings_rows, clip, live)
                v = await self.redis.rpop("goal_clips:incoming")
        except Exception as e:
            log.warning("live_tracker: clip pump failed: %r", e)

    @_clip_pump.before_loop
    async def _before_pump(self):
        await self.bot.wait_until_ready()

    async def _mark_clip(self, clip_id, status: str):
        """Set a goal_clips row's status (and posted_at when 'posted'). Best-effort."""
        try:
            async with self.db.worker_session() as s:
                await s.execute(text(
                    "UPDATE goal_clips SET status=:st, "
                    "posted_at=CASE WHEN :st='posted' THEN now() ELSE posted_at END "
                    "WHERE id=:i"), {"st": status, "i": clip_id})
                await s.commit()
        except Exception:
            pass

    async def _caption_for_clip(self, text_en: str, live: list[dict]) -> tuple[bool, int, str]:
        """Vet a Fox clip against the currently-live match(es) AND translate it, in one call.

        Returns (is_goal, match_idx, caption). match_idx is the 1-based index (into ``live``)
        of the match the clip is about, or 0 when it's about none of them — a DIFFERENT game,
        a past tournament/nostalgia, a meme/promo, fan-cams or studio talk from another match.
        is_goal flags whether a goal was scored (for routing to the goal channel). The caption
        is plain Spanish: no links, no @mentions, no platform references. Fails CLOSED
        ((False, 0, …) → skip) on empty text or any LLM error — the web stream still announces
        the goal, so a dropped bonus clip is cheap; a wrong/off-topic clip is what we want gone."""
        src = re.sub(r"https?://\S+", "", text_en or "")   # links (t.co etc.)
        src = re.sub(r"@\w+", "", src)                      # @handles (X references)
        src = re.sub(r"\s+", " ", src).strip()
        if not src:
            return (False, 0, "")  # no text → can't vet → skip
        listing = "\n".join(f"{i + 1}) {m.get('home_name')} vs {m.get('away_name')}"
                            for i, m in enumerate(live or [])) or "(ninguno)"
        sys = (
            "Recibes el texto de una publicación de video de una cuenta de fútbol y una lista "
            "NUMERADA de PARTIDOS EN VIVO ahora mismo. Devuelve:\n"
            "• match = el NÚMERO del partido en vivo del que trata la publicación (esos "
            "equipos). Pon match=0 si NO trata de ninguno de los partidos listados: otro "
            "partido o equipos, un torneo pasado o nostalgia, un meme/promoción/genérico, o "
            "aficionados/estudio de otro juego.\n"
            "• is_goal = true SOLO si el texto describe un GOL ANOTADO (marca, anota, golazo, "
            "de cabeza, definición, doblete, hat-trick, o la repetición/jugada de ese gol). "
            "Pon is_goal=false para atajadas, tiros fallados, gol ANULADO/VAR, tarjetas, "
            "previas, entrevistas, reacciones de afición sin gol, o gráficos.\n"
            "• es = la traducción al español (es-MX) como frase simple: sin comillas, sin "
            "enlaces, sin menciones (@), sin referencias a X/Twitter/Fox; conserva emojis y "
            "nombres propios."
        )
        user = f"PARTIDOS EN VIVO AHORA:\n{listing}\n\nTEXTO DE LA PUBLICACIÓN:\n{src}"
        try:
            data = await self.llm.generate_structured(user, CLIP_RELAY_SCHEMA, system_prompt=sys)
            if isinstance(data, dict) and "is_goal" in data and "match" in data:
                es = str(data.get("es") or "").strip() or src
                try:
                    idx = int(data.get("match") or 0)
                except (TypeError, ValueError):
                    idx = 0
                return (bool(data["is_goal"]), idx, es)
        except Exception:
            pass
        return (False, 0, src)  # fail closed — don't post what we couldn't vet

    async def _relay_clip(self, settings_rows, clip, live):
        """Post one uploaded Fox clip as a video with a Spanish caption. Routing:
        EVERY clip about a live match → that match's game thread (under lt_channel_id, with the
        live embeds); GOAL clips → ALSO the goal channel (lt_goal_channel_id). Clips not about
        any live match (other games, nostalgia, memes) are dropped. The X stream owns the video;
        the web stream still owns the textual goal announcements."""
        clip_id = clip.get("clip_id")
        if not live:
            # No game in window — drop it so an off-hours clip never posts.
            await self._mark_clip(clip_id, "expired")
            return
        file_path, row_text = None, ""
        try:
            async with self.db.worker_session() as s:
                row = (await s.execute(
                    text("SELECT file_path, text FROM goal_clips WHERE id=:i"), {"i": clip_id})).mappings().first()
                if row:
                    file_path = row["file_path"]
                    row_text = row["text"] or ""
        except Exception as e:
            log.warning("live_tracker: clip lookup failed for clip %s: %r", clip_id, e)
        if not file_path or not os.path.exists(file_path):
            log.warning("live_tracker: clip %s file missing — skipping", clip_id)
            await self._mark_clip(clip_id, "expired")
            return
        # Prefer the Redis payload text; fall back to the goal_clips row (always populated at
        # ingest). One LLM call: which live match it's about, whether it's a goal, + translate.
        src = clip.get("text") or row_text
        is_goal, idx, es = await self._caption_for_clip(src, live)
        if idx < 1 or idx > len(live):
            log.info("live_tracker: clip %s skipped — not about a live match (match=%s) — %r",
                     clip_id, idx, (src or "")[:80])
            await self._mark_clip(clip_id, "skipped")
            return
        m = live[idx - 1]  # the live match this clip is about → its game thread
        # Dedup near-identical reposts: Fox posts the same goal as several tweets (different
        # tweet_ids, same/near text), so tweet-id dedup misses them. First clip of a given
        # text signature wins for a few hours; later identical posts are dropped.
        sig = re.sub(r"[^a-z0-9]+", "", (src or "").lower())[:120]
        if sig:
            try:
                if not await self.redis.set(f"clips:textseen:{sig}", str(clip_id), nx=True, ex=3 * 3600):
                    log.info("live_tracker: clip %s skipped — duplicate of an already-posted clip", clip_id)
                    await self._mark_clip(clip_id, "duplicate")
                    return
            except Exception:
                pass
        cap = f"🎥 {es}" if es else "🎥 ⚽"
        log.info("live_tracker: relaying clip %s (is_goal=%s match=%s) — %r",
                 clip_id, is_goal, m["id"], cap[:90])
        await self._mark_clip(clip_id, "posted")
        for guild_id, settings_json in settings_rows:
            settings = settings_json if isinstance(settings_json, dict) else _safe_json(settings_json)
            if not settings.get("lt_enabled"):
                continue
            guild = self.bot.get_guild(int(guild_id))
            if guild is None:
                continue
            # (a) game thread under lt_channel_id — EVERY match clip (alongside the live embeds)
            ch_id = settings.get("lt_channel_id")
            live_ch = guild.get_channel(int(ch_id)) if ch_id else None
            if live_ch is not None:
                thread = await self._match_thread(live_ch, guild_id, m, None)
                target = thread or live_ch
                try:
                    await target.send(content=cap[:1900],
                                      file=discord.File(file_path, filename=f"gol_{clip_id}.mp4"))
                except discord.HTTPException as e:
                    log.warning("live_tracker: clip thread post failed (guild %s): %r", guild_id, e)
            # (b) goal channel — GOAL clips only
            gch_id = settings.get("lt_goal_channel_id")
            gch = guild.get_channel(int(gch_id)) if (is_goal and gch_id) else None
            if gch is not None:
                try:
                    await gch.send(content=cap[:1900],
                                   file=discord.File(file_path, filename=f"gol_{clip_id}.mp4"))
                except discord.HTTPException as e:
                    log.warning("live_tracker: clip goal-channel post failed (guild %s): %r", guild_id, e)
        # Web "Now" feed = highlights → push the clip only for goals.
        if is_goal:
            await self._push_event({"type": "goal_clip", "match_id": m["id"],
                                    "video_url": f"/api/v1/goal-clips/{clip_id}/video",
                                    "text": cap, "ts": int(time.time())})

    async def _announce_new_goals(self, settings_rows, new_goals):
        """Announce each new goal once to every enabled guild's goal channel. The web stream
        is the sole goal decision-maker: it names the side that scored, the scorer + minute,
        and a running scoreline tallied in MINUTE order (so a goal surfaced out of order still
        shows its true score — never an impossible line). Dedup + restart-safety come from the
        persisted live:seen:{mid} set and the goal budget upstream in _publish_live_events.
        Goals surfaced together in one tick are announced in MINUTE order (cross-tick lag,
        where the AI indexes an early goal several ticks late, can't be reordered)."""
        for g in sorted(new_goals or [], key=lambda x: _minute_sort_key(x.get("minute"))):
            home, away = g["home"], g["away"]
            is_home = str(g.get("team") or "").strip().lower() in ("home", "local")
            scoring_team = home if is_home else away
            scorer = _known(g["ev"].get("player"))
            minute = _clean_minute(g["ev"])
            who = f" · {scorer} {minute}".rstrip() if scorer else (f" · {minute}" if minute else "")
            msg = f"⚽ ¡GOOOL de **{scoring_team}**!{who} · {home} {g['h']}–{g['a']} {away}"
            for guild_id, settings_json in settings_rows:
                settings = settings_json if isinstance(settings_json, dict) else _safe_json(settings_json)
                if not settings.get("lt_enabled") or not settings.get("lt_goal_channel_id"):
                    continue
                guild = self.bot.get_guild(int(guild_id))
                channel = guild.get_channel(int(settings["lt_goal_channel_id"])) if guild else None
                if channel is None:
                    continue
                goal_role_id = settings.get("lt_goal_role_id")
                ping = f"<@&{int(goal_role_id)}> " if goal_role_id else ""
                try:
                    await channel.send(content=ping + msg,
                                       allowed_mentions=discord.AllowedMentions(roles=True))
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
            # than a growing pile of hourly posts — but ONLY before the tournament has
            # started. Once games have been played, the feed belongs to the last match
            # and must survive until the next game's window wipes it (_fresh_window_wipe).
            async with self.db.worker_session() as s:
                started = bool((await s.execute(
                    text("SELECT count(*) FROM matches WHERE finished = true")
                )).scalar())
            if not started:
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
            user += await self._match_context(m)
            grounded = await provider.generate_response(
                [LLMMessage(role="user", content=user)],
                system_prompt=sys,
                tools=[{"google_search": {}}],
            )
            grounded = grounded if isinstance(grounded, str) else json.dumps(grounded)
            return await self._parse_score(grounded)
        except Exception:
            return None

    async def _parse_score(self, grounded: str) -> dict | None:
        """Second leg of the AI pipeline: turn grounded prose into strict score JSON.
        Shared by the live poll and the post-match reconcile read."""
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
        return None

    async def _ai_final(self, provider, m: dict) -> dict | None:
        """Grounded re-read of a FINISHED match's definitive full-time score from
        post-match reports (not live minute-by-minute, not a half-time recap). Used by
        the reconcile sweep an hour after the game ends, when the result is settled."""
        try:
            from services.llm import LLMMessage
            sys = self.llm.load_prompt("live_tracker", "score_fetch", "system_prompt") or (
                "Eres un asistente que verifica el resultado FINAL de un partido del Mundial 2026 "
                "usando la búsqueda en internet. Responde ÚNICAMENTE en español (es-MX)."
            )
            user = (
                f"El partido {m['home_name']} vs {m['away_name']} del Mundial 2026 YA TERMINÓ hace cerca "
                f"de una hora. Usando la búsqueda en crónicas POSTERIORES al partido (resultado final, NO "
                f"transmisiones en vivo ni resúmenes del medio tiempo), dame el MARCADOR FINAL definitivo a "
                f"tiempo completo y la lista completa de goles (goleador y minuto, incluidos los del tiempo "
                f"añadido y la prórroga). Tengo registrado {m['home_name']} {m.get('hs')}–{m.get('as_')} "
                f"{m['away_name']}; confírmalo, o corrígelo SOLO si varias fuentes coinciden claramente en "
                f"otro marcador final. Marca finished=true y confianza alta únicamente si las fuentes "
                f"concuerdan en el resultado definitivo."
            )
            grounded = await provider.generate_response(
                [LLMMessage(role="user", content=user)],
                system_prompt=sys,
                tools=[{"google_search": {}}],
            )
            grounded = grounded if isinstance(grounded, str) else json.dumps(grounded)
            return await self._parse_score(grounded)
        except Exception:
            return None

    async def _reconcile_finals(self, provider):
        """Re-verify committed finals ~1h after the match ends and correct any score that
        missed a late goal at commit time. The live commit can lock a score during 2nd-half
        stoppage or right at FT, before a 90'+ goal is indexed; an hour later the result is
        settled, so one grounded re-read of the FINAL fixes those misses, then standings /
        bracket / predictions are recomputed. Fires at most once per match — the Redis
        marker is set only after a confident reading, so a failed read retries next tick."""
        if not provider or not self.redis:
            return
        async with self.db.worker_session() as s:
            finals = [dict(r) for r in (await s.execute(_RECONCILE_SQL)).mappings().all()]
        pending = []
        for m in finals:
            try:
                if await self.redis.get(f"live:reconciled:{m['id']}"):
                    continue
            except Exception:
                pass
            pending.append(m)
        if not pending:
            return
        changed = False
        async with self.db.worker_session() as s:
            for m in pending:
                r = await self._ai_final(provider, m)
                if not r or not r.get("finished"):
                    continue
                hs, as_ = r.get("home_score"), r.get("away_score")
                if hs is None or as_ is None or float(r.get("confidence", 0)) < 0.8:
                    continue
                # Confident, settled reading obtained → don't reconcile this match again.
                try:
                    await self.redis.set(f"live:reconciled:{m['id']}", "1", ex=86400)
                except Exception:
                    pass
                if int(hs) == int(m["hs"]) and int(as_) == int(m["as_"]):
                    continue
                await s.execute(
                    text("""UPDATE matches
                            SET home_score = :hs, away_score = :as_,
                                home_pens = COALESCE(:hp, home_pens),
                                away_pens = COALESCE(:ap, away_pens), time_elapsed = 'FT'
                            WHERE id = :id AND finished = true"""),
                    {"hs": int(hs), "as_": int(as_),
                     "hp": r.get("home_pens"), "ap": r.get("away_pens"), "id": m["id"]},
                )
                changed = True
                log.warning("live_tracker: reconcile corrected match %s from %s-%s to %s-%s "
                            "(late goal missed at commit)", m["id"], m["hs"], m["as_"], int(hs), int(as_))
            if changed:
                await self._recompute_standings(s)
                await self._resolve_bracket(s)
                await self._rescore(s)
            await s.commit()

    async def _match_context(self, m: dict) -> str:
        """Known-state block injected into the AI poll so each tick builds on the
        previous ones instead of rediscovering the match from scratch: the score we
        hold, the current state, and every event already reported. The model uses it
        to report only what is NEW and to keep names/minutes consistent (which also
        makes the dedup keys stable)."""
        known = f"{m['home_name']} {m.get('hs') or 0}–{m.get('as_') or 0} {m['away_name']}"
        te = str(m.get("te") or "").strip()
        if te:
            known += f" · estado: {_state_es(te)}"
        lines = []
        if self.redis:
            try:
                lines = [_dec(x) for x in await self.redis.lrange(f"live:ctx:{m['id']}", 0, 29)]
            except Exception:
                lines = []
        ctx = ("\n\nCONTEXTO DE TICKS ANTERIORES (ya reportado a los usuarios):\n"
               f"- Marcador conocido: {known}\n")
        if lines:
            ctx += "\n".join(f"- {l}" for l in lines) + "\n"
        # Minute-aware steering. The grounded search's dominant failure mode is
        # settling on a well-indexed HALF-TIME RECAP and re-reporting the old score,
        # so the live score never advances past the break. Tell the model roughly how
        # far the match is (from wall-clock since kickoff) and force it to hunt for any
        # goal AFTER the last minute we already know — that's what reliably surfaces
        # second-half / stoppage goals instead of stale recaps.
        mins = m.get("mins_since_ko")
        last_min = 0
        for l in lines:
            for mm in re.findall(r"(\d{1,3})(?=['′+])", l):
                last_min = max(last_min, int(mm))
        if isinstance(mins, (int, float)):
            wall = int(mins)
            est = max(0, wall - 15)  # discount the ~15' half-time break
            ctx += (f"\nRELOJ: han pasado ~{wall} min desde el inicio (incluye el descanso de ~15'), "
                    f"así que el juego va por ~minuto {est} o está por terminar. ")
        ctx += (f"BUSCA ACTIVAMENTE en fuentes de minuto a minuto cualquier GOL o evento "
                f"POSTERIOR al minuto {last_min} (segundo tiempo y tiempo añadido); el marcador "
                f"PUDO cambiar desde el último tick. NO te quedes con resúmenes del medio tiempo. "
                f"Reporta el estado actual completo y presta especial atención a lo NUEVO. "
                f"Mantén nombres y minutos consistentes con lo ya reportado; un gol ya reflejado en "
                f"el marcador conocido NO es nuevo. NO declares el partido terminado a menos que las "
                f"fuentes confirmen el pitido final (FT). Solo contradice el contexto si las fuentes "
                f"lo corrigen claramente.")
        return ctx

    async def _ctx_add(self, match_id: int, line: str):
        """Append a reported event to the match's context memory (capped, 6h TTL)."""
        if not self.redis:
            return
        try:
            await self.redis.rpush(f"live:ctx:{match_id}", line)
            await self.redis.ltrim(f"live:ctx:{match_id}", -30, -1)
            await self.redis.expire(f"live:ctx:{match_id}", 21600)
        except Exception:
            pass

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
            committed = False
            if auto_commit and r.get("finished") and float(r.get("confidence", 0)) >= threshold:
                # Three guards against ending the stream early or with a WRONG score,
                # while still ending it promptly once the game is really over:
                # 1. debounce + score match — TWO consecutive polls must agree it's
                #    finished WITH THE SAME score (a flaky/hallucinated final never
                #    repeats identically, so it can't commit);
                # 2. physical floor — a match can't truly end before ~kickoff+120'.
                #    Two 45' halves + a 15' break already run to ~105'; second-half
                #    stoppage routinely pushes the final whistle (and its late goals —
                #    the 90'+ winners) past that. 105' let finals commit DURING 2nd-half
                #    stoppage and lock a pre-stoppage score (e.g. 2-0 before two 90'+
                #    goals made it 3-1). 120' covers full stoppage so those goals land
                #    before we ever commit. The grounded AI reports finished=false while
                #    a knockout is in ET, so this flat floor is safe there too.
                # Once both pass, finished=true commits and polling stops entirely.
                if await self._final_confirmed(m["id"], r["home_score"], r["away_score"]):
                    res = await s.execute(
                        text("""
                            UPDATE matches
                            SET home_score = :hs, away_score = :as_, finished = true,
                                home_pens = :hp, away_pens = :ap, time_elapsed = 'FT'
                            WHERE id = :id AND finished = false
                              AND kickoff_at <= now() - interval '120 minutes'
                        """),
                        {"hs": int(r["home_score"]), "as_": int(r["away_score"]),
                         "hp": r.get("home_pens"), "ap": r.get("away_pens"), "id": m["id"]},
                    )
                    committed = bool(res.rowcount)
                    if not committed:
                        log.info("live_tracker: AI reported final for match %s before 120' — holding commit", m["id"])
            else:
                await self._clear_final_pending(m["id"])
            if not committed:
                # Write time_elapsed only when there is something REAL to say: a
                # minute, or a status while the game hasn't started. A held/early
                # "finished" must NOT touch it (it used to paint "90'+" pre-game).
                if r.get("minute"):
                    te = str(r.get("minute"))[:20]
                elif not r.get("finished"):
                    te = str(r.get("status") or "")[:20]
                else:
                    te = None  # held final: keep whatever minute is already stored
                hs, as_ = r.get("home_score"), r.get("away_score")
                if (hs is not None and as_ is not None
                        and str(r.get("status") or "").lower() != "notstarted"
                        and float(r.get("confidence", 0)) >= 0.6):
                    # Keep the LIVE score on the matches row too (final commit above
                    # only fires at FT) — embeds/boards read from here. GREATEST
                    # guards against AI wobble briefly walking a score backwards.
                    await s.execute(
                        text("""
                            UPDATE matches
                            SET home_score = GREATEST(COALESCE(home_score, 0), :hs),
                                away_score = GREATEST(COALESCE(away_score, 0), :as_),
                                time_elapsed = COALESCE(:te, time_elapsed)
                            WHERE id = :id AND finished = false
                        """),
                        {"hs": int(hs), "as_": int(as_), "te": te, "id": m["id"]},
                    )
                elif te:
                    await s.execute(
                        text("UPDATE matches SET time_elapsed = :te WHERE id = :id AND finished = false"),
                        {"te": te, "id": m["id"]},
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
            state = "FINAL" if m["finished"] else _state_es(m["te"]).upper()
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
        state = "🏁 FINAL" if m["finished"] else f"🔴 {_state_es(m['te']).upper()}"
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


# time_elapsed holds either a minute ("47'") or a raw AI status word — map the
# status words to user-facing Spanish; minutes pass through untouched.
_STATE_ES = {
    "notstarted": "Por comenzar", "not_started": "Por comenzar",
    "live": "En juego", "inprogress": "En juego", "in_progress": "En juego",
    "halftime": "Descanso", "ht": "Descanso",
    "penalties": "Penales", "finished": "Final", "ft": "Final", "fulltime": "Final",
}


def _dec(v):
    """Decode a Redis reply to str — the bot's client returns bytes (decode_responses
    is off), so string comparisons on raw replies (b'2-2' == '2-2') silently fail."""
    return v.decode() if isinstance(v, (bytes, bytearray)) else v


def _state_es(te) -> str:
    t = str(te or "").strip()
    return _STATE_ES.get(t.lower().replace(" ", "_"), t) or "En juego"


def _event_key(ev, etype) -> str:
    """Stable dedup key for an event — tolerant to AI wording wobble across polls
    ("23" vs "23'", "R. Jiménez" vs "Raúl Jiménez", accents, middle names)."""
    minute = re.sub(r"[^0-9+]", "", str(ev.get("minute") or ""))
    player = str(ev.get("player") or "").strip().lower()
    player = unicodedata.normalize("NFKD", player).encode("ascii", "ignore").decode()
    parts = player.replace(".", " ").split()
    player = parts[-1] if parts else ""
    team = str(ev.get("team") or "").strip().lower()
    return f"{etype}|{minute}|{team}|{player}"


def _minute_sort_key(minute_str) -> tuple[int, int]:
    """Sort key for a match minute: "90+3'"→(90,3), "74'"→(74,0); blank/vague→(9999,0)
    so they sort last and keep the AI's original array order as the tiebreak."""
    s = re.sub(r"[^0-9+]", "", str(minute_str or ""))
    if not s:
        return (9999, 0)
    base, _, extra = s.partition("+")
    try:
        b = int(base) if base else 9999
    except ValueError:
        b = 9999
    try:
        e = int(extra) if extra else 0
    except ValueError:
        e = 0
    return (b, e)


def _running_scores(events, status: str = "") -> dict[str, tuple[int, int]]:
    """Map each goal event's _event_key → the running (home, away) score AFTER it.

    Goals are tallied in MINUTE order (not the AI's array/detection order), so a goal's
    displayed scoreline is its true score even when goals are detected out of order across
    polls — the web stream owns the score, the announcement just reads this map. Shootout
    kicks (status 'penalties') are skipped: that result is shown via home_pens/away_pens,
    not the 90-minute score. An own_goal credits the OPPOSITE side of ev['team']."""
    if str(status or "").strip().lower() in ("penalties", "shootout", "penales"):
        return {}
    goals = []
    for ev in (events or []):
        if not isinstance(ev, dict):
            continue
        et = _norm_event_type(ev.get("type"))
        if et in ("goal", "own_goal", "penalty_goal"):
            goals.append((ev, et))
    goals.sort(key=lambda ge: _minute_sort_key(ge[0].get("minute")))
    h = a = 0
    out: dict[str, tuple[int, int]] = {}
    for ev, et in goals:
        is_home = str(ev.get("team") or "").strip().lower() in ("home", "local")
        if et == "own_goal":
            is_home = not is_home  # an own goal credits the other team
        if is_home:
            h += 1
        else:
            a += 1
        out[_event_key(ev, et)] = (h, a)
    return out


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


# Every event line says WHAT happened in words — emoji alone is ambiguous
# (🟥 read as "red ball", 🔄 as "update").
_EVENT_LABEL_ES = {
    "goal": "GOL", "own_goal": "GOL en propia puerta", "penalty_goal": "GOL de penal",
    "penalty_miss": "Penal fallado", "yellow": "Tarjeta amarilla", "red": "Tarjeta roja",
    "second_yellow": "Segunda amarilla (expulsión)", "substitution": "Cambio",
    "var": "Revisión del VAR",
}

_UNKNOWN_WORDS = ("desconocido", "unknown", "n/a", "na", "unknown desconocido", "tbd",
                  "none", "null", "n/d", "nd", "-", "—", "no especificado", "se desconoce")


def _known(value) -> str:
    """The value, or '' when it's a placeholder the AI uses for 'no idea'."""
    s = str(value or "").strip()
    return "" if s.lower() in _UNKNOWN_WORDS else s


def _clean_minute(ev) -> str:
    """Minute when it really is one ("67'", "45+2'"); '' for vague values ("2T", "HT")."""
    raw = str(ev.get("minute") or "").strip().rstrip("'")
    return f"{raw}'" if re.fullmatch(r"\d{1,3}(\+\d{1,2})?", raw or "") else ""


def _fmt_event(ev, etype, home, away) -> str:
    """One human line, e.g. \"🟥 Tarjeta roja 46' — S. Sithole (South Africa) — Falta\"."""
    emoji = _EVENT_EMOJI.get(etype, "•")
    label = _EVENT_LABEL_ES.get(etype, etype.replace("_", " "))
    minute = _clean_minute(ev)
    player = _known(ev.get("player"))
    detail = _known(ev.get("detail"))
    team = _team_name(ev, home, away)
    line = f"{emoji} {label}" + (f" {minute}" if minute else "")
    who = player or (team if etype in ("goal", "own_goal", "penalty_goal") else "")
    if who:
        line += f" — {who}"
    if player and team:
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
