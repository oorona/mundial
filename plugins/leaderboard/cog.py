"""
leaderboard — worker cog: keeps a single auto-updated standings message in a channel
and publishes refresh events for the web SSE stream.

The bot process has no access to the backend ORM, so all DB access here is raw SQL via
the RLS-bypassed worker session (bot.services.db). The bot is a single AutoShardedBot
process, so this is the only writer.
"""
import json
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import text

DEFAULT_ACCENT = "#f59e0b"

# Sentinel id of the machine player (mirrors ai_player.AI_USER_ID). Excluded from a
# server's board when that server turns the AI player off (ai_player_enabled = false).
AI_USER_ID = 1

# Mexico City is a fixed UTC-6 year-round (Mexico abolished DST in 2022).
CDMX = timezone(timedelta(hours=-6))

_STANDINGS_SQL = text("""
    SELECT p.user_id AS user_id, p.username AS username, p.points AS points,
           p.pred_home AS pred_home, p.pred_away AS pred_away,
           m.finished AS finished, m.home_score AS home_score, m.away_score AS away_score
    FROM predictions p JOIN matches m ON m.id = p.match_id
    WHERE p.guild_id = :gid
""")

# Same, restricted to matches kicking off in a [start, end) window (yesterday CDMX).
_DAILY_SQL = text("""
    SELECT p.user_id AS user_id, p.username AS username, p.points AS points,
           p.pred_home AS pred_home, p.pred_away AS pred_away,
           m.finished AS finished, m.home_score AS home_score, m.away_score AS away_score
    FROM predictions p JOIN matches m ON m.id = p.match_id
    WHERE p.guild_id = :gid AND m.kickoff_at >= :start AND m.kickoff_at < :end
""")

# Today's matches with names + FIFA codes (compact headers for the picks board).
_TODAY_MATCHES_SQL = text("""
    SELECT m.id AS id,
           COALESCE(ht.name_en, m.home_team_label) AS home,
           COALESCE(at.name_en, m.away_team_label) AS away,
           UPPER(COALESCE(ht.fifa_code, left(COALESCE(ht.name_en, m.home_team_label, '?'), 3))) AS home_code,
           UPPER(COALESCE(at.fifa_code, left(COALESCE(at.name_en, m.away_team_label, '?'), 3))) AS away_code,
           m.finished AS finished, m.home_score AS home_score, m.away_score AS away_score,
           m.kickoff_at AS kickoff_at
    FROM matches m
    LEFT JOIN teams ht ON ht.id = m.home_team_id
    LEFT JOIN teams at ON at.id = m.away_team_id
    WHERE m.kickoff_at >= :start AND m.kickoff_at < :end
    ORDER BY m.kickoff_at, m.id
""")

# Each participant's pick per match in the window (today CDMX).
_TODAY_PICKS_SQL = text("""
    SELECT p.user_id AS user_id, p.username AS username, p.points AS points,
           p.match_id AS match_id, p.pred_home AS pred_home, p.pred_away AS pred_away
    FROM predictions p JOIN matches m ON m.id = p.match_id
    WHERE p.guild_id = :gid AND m.kickoff_at >= :start AND m.kickoff_at < :end
""")


def _cdmx_yesterday_window():
    """(start, end, date) covering the previous CDMX calendar day."""
    y = (datetime.now(CDMX) - timedelta(days=1)).date()
    start = datetime(y.year, y.month, y.day, tzinfo=CDMX)
    return start, start + timedelta(days=1), y


def _cdmx_today_window():
    """(start, end, date) covering the current CDMX calendar day."""
    today = datetime.now(CDMX).date()
    start = datetime(today.year, today.month, today.day, tzinfo=CDMX)
    return start, start + timedelta(days=1), today


class Leaderboard(commands.Cog):
    """Keeps each server's quiniela standings posted and auto-updated in its leaderboard channel, and publishes refresh events to the web/Activity (worker)."""

    SETTINGS_SCHEMA = {
        "id": "leaderboard",
        "label": "leaderboard.settings.label",
        "description": "leaderboard.settings.desc",
        "fields": [
            {"key": "leaderboard_enabled", "type": "boolean", "label": "leaderboard.settings.enabled", "default": False},
            {"key": "leaderboard_channel_id", "type": "channel_select", "label": "leaderboard.settings.channel", "default": None},
            {"key": "leaderboard_accent", "type": "color", "label": "leaderboard.settings.accent", "default": DEFAULT_ACCENT},
        ],
    }

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.services.db
        self.redis = getattr(bot.services, "redis", None)
        self.refresh_loop.start()

    def cog_unload(self):
        self.refresh_loop.cancel()

    @tasks.loop(seconds=120)
    async def refresh_loop(self):
        if not self.db:
            return
        async with self.db.worker_session() as session:
            rows = (await session.execute(text("SELECT guild_id, settings_json FROM guild_settings"))).all()
            for guild_id, settings_json in rows:
                settings = self._parse(settings_json)
                if not settings.get("leaderboard_enabled") or not settings.get("leaderboard_channel_id"):
                    continue
                ch = settings["leaderboard_channel_id"]
                guild = self.bot.get_guild(int(guild_id))
                if guild is None:
                    continue  # not in cache → can't post or resolve display names anyway
                ai_enabled = settings.get("ai_player_enabled", True)
                ai_name = settings.get("ai_player_name") or "🤖 IA"
                # Global board (all matches, cumulative).
                standings = self._apply_display(guild, await self._standings(session, guild_id, ai_enabled), ai_name)
                # Share resolved display names so the web/Activity boards match Discord.
                await self._publish_names(guild_id, standings)
                g_mid = await self._publish(guild_id, ch, settings,
                                            self._embed(settings, standings), "leaderboard_message_id")
                # Daily board (only the previous CDMX-day's matches), posted to the same channel.
                daily, day = await self._daily_standings(session, guild_id, ai_enabled)
                d_mid = await self._publish(guild_id, ch, settings,
                                            self._daily_embed(settings, self._apply_display(guild, daily, ai_name), day),
                                            "leaderboard_daily_message_id")
                # Today board (today's CDMX matches + each player's pick per game), same channel.
                t_matches, t_players, tday = await self._today_board(session, guild_id, ai_enabled)
                t_mid = await self._publish(guild_id, ch, settings,
                                            self._today_embed(settings, t_matches,
                                                              self._apply_display(guild, t_players, ai_name), tday),
                                            "leaderboard_today_message_id")
                changed = False
                if g_mid:
                    settings["leaderboard_message_id"] = str(g_mid); changed = True
                if d_mid:
                    settings["leaderboard_daily_message_id"] = str(d_mid); changed = True
                if t_mid:
                    settings["leaderboard_today_message_id"] = str(t_mid); changed = True
                if changed:
                    await session.execute(
                        text("UPDATE guild_settings SET settings_json = CAST(:j AS json) WHERE guild_id = :g"),
                        {"j": json.dumps(settings), "g": guild_id},
                    )
            await session.commit()

    @refresh_loop.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    # Slash command (/clasificacion) intentionally removed — the leaderboard is viewed
    # in the Discord Activity now. The worker loop above still keeps the channel board
    # updated. Only the framework's /status command remains bot-side.

    # ── Helpers ──────────────────────────────────────────────────────────────
    @staticmethod
    def _parse(settings_json) -> dict:
        if isinstance(settings_json, str):
            try:
                return json.loads(settings_json) or {}
            except Exception:
                return {}
        return dict(settings_json or {})

    async def _standings(self, session, guild_id, ai_enabled: bool = True) -> list[dict]:
        res = (await session.execute(_STANDINGS_SQL, {"gid": int(guild_id)})).mappings().all()
        return self._reduce(res, ai_enabled)

    async def _daily_standings(self, session, guild_id, ai_enabled: bool = True):
        """Standings from only the previous CDMX-day's matches; returns (rows, date)."""
        start, end, day = _cdmx_yesterday_window()
        res = (await session.execute(
            _DAILY_SQL, {"gid": int(guild_id), "start": start, "end": end}
        )).mappings().all()
        return self._reduce(res, ai_enabled), day

    async def _today_board(self, session, guild_id, ai_enabled: bool = True):
        """Today's CDMX matches plus each participant's pick per match; returns
        (matches, players, date). Today's picks are already locked (midnight CDMX),
        so publishing them leaks nothing."""
        start, end, day = _cdmx_today_window()
        matches = (await session.execute(
            _TODAY_MATCHES_SQL, {"start": start, "end": end}
        )).mappings().all()
        res = (await session.execute(
            _TODAY_PICKS_SQL, {"gid": int(guild_id), "start": start, "end": end}
        )).mappings().all()
        players: dict[int, dict] = {}
        for r in res:
            if not ai_enabled and r["user_id"] == AI_USER_ID:
                continue
            u = players.setdefault(r["user_id"], {
                "user_id": r["user_id"], "username": None, "points": 0, "picks": {},
            })
            if r["username"]:
                u["username"] = r["username"]
            u["points"] += r["points"] or 0
            u["picks"][r["match_id"]] = (r["pred_home"], r["pred_away"])
        rows = sorted(players.values(), key=lambda x: (-x["points"], (x["username"] or "").lower()))
        for r in rows:
            if not r["username"]:
                r["username"] = f"Jugador {str(r['user_id'])[-4:]}"
        return matches, rows, day

    @staticmethod
    def _reduce(res, ai_enabled: bool = True) -> list[dict]:
        per_user: dict[int, dict] = {}
        for r in res:
            # AI player (user_id=1) is excluded from this guild's board when disabled.
            if not ai_enabled and r["user_id"] == AI_USER_ID:
                continue
            u = per_user.setdefault(r["user_id"], {
                "user_id": r["user_id"], "username": None,
                "points": 0, "exactos": 0, "aciertos": 0,
            })
            if r["username"]:
                u["username"] = r["username"]
            u["points"] += r["points"] or 0
            if r["finished"] and r["home_score"] is not None and r["away_score"] is not None:
                if (r["points"] or 0) > 1:  # >1 = beat the 1-pt participation floor (a real correct pick)
                    u["aciertos"] += 1
                if r["pred_home"] == r["home_score"] and r["pred_away"] == r["away_score"]:
                    u["exactos"] += 1
        rows = sorted(per_user.values(), key=lambda x: (x["points"], x["exactos"], x["aciertos"]), reverse=True)
        for i, r in enumerate(rows, 1):
            r["position"] = i
            if not r["username"]:
                r["username"] = f"Jugador {str(r['user_id'])[-4:]}"
        return rows

    @staticmethod
    def _apply_display(guild, rows: list[dict], ai_name: str | None = None) -> list[dict]:
        """Attach each user's guild display name (nickname / global display) for the board.

        Resolved from the member cache (the bot has the members intent). The AI player
        (user_id=1) is not a real member, so it uses the guild's CURRENT ``ai_player_name``
        setting (not the possibly-stale name stored on its prediction rows). Humans who left
        the guild fall back to the username stored on the prediction."""
        for r in rows:
            if r["user_id"] == AI_USER_ID:
                if ai_name:
                    r["display"] = ai_name
                continue
            member = guild.get_member(int(r["user_id"])) if guild else None
            if member is not None:
                r["display"] = member.display_name
        return rows

    @staticmethod
    def _name(r: dict) -> str:
        return r.get("display") or r.get("username") or f"Jugador {str(r['user_id'])[-4:]}"

    _NAME_W = 16
    _MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

    def _table(self, standings: list[dict]) -> str:
        """Podium line (top 3 with medals) + a monospaced, column-aligned table (top 15)."""
        top = standings[:15]
        podium = "  ".join(
            f"{self._MEDALS[r['position']]} **{discord.utils.escape_markdown(self._name(r))}**"
            for r in top[:3]
        )
        header = f"{'#':>2}  {'Jugador':<{self._NAME_W}} {'Pts':>4} {'Ex':>3} {'Ac':>3}"
        lines = [header, "─" * len(header)]
        for r in top:
            name = self._name(r).replace("`", "'").replace("\n", " ").strip()
            if len(name) > self._NAME_W:
                name = name[: self._NAME_W - 1] + "…"
            lines.append(
                f"{r['position']:>2}  {name:<{self._NAME_W}} "
                f"{r['points']:>4} {r['exactos']:>3} {r['aciertos']:>3}"
            )
        table = "```\n" + "\n".join(lines) + "\n```"
        return f"{podium}\n{table}" if podium else table

    def _embed(self, settings: dict, standings: list[dict]) -> discord.Embed:
        embed = discord.Embed(
            title="🏆 Clasificación de la quiniela",
            color=_color(settings.get("leaderboard_accent") or DEFAULT_ACCENT))
        embed.description = self._table(standings) if standings else "Aún no hay pronósticos puntuados."
        embed.set_footer(text="Pts = puntos · Ex = exactos · Ac = aciertos · Última actualización")
        embed.timestamp = datetime.now(timezone.utc)  # shown next to the footer; updates every refresh
        return embed

    def _daily_embed(self, settings: dict, standings: list[dict], day) -> discord.Embed:
        embed = discord.Embed(
            title=f"📅 Clasificación de ayer ({day.isoformat()})",
            color=_color(settings.get("leaderboard_accent") or DEFAULT_ACCENT))
        embed.description = self._table(standings) if standings else "No hubo partidos ayer."
        embed.set_footer(text="Pts = puntos · Ex = exactos · Ac = aciertos · Solo partidos de ayer (CDMX) · Última actualización")
        embed.timestamp = datetime.now(timezone.utc)  # shown next to the footer; updates every refresh
        return embed

    _PICK_W = 7  # column width: fits "MEX-RSA" headers and "12-10*" picks

    def _today_embed(self, settings: dict, matches, players: list[dict], day) -> discord.Embed:
        """Today's picks board: the day's matches (result or CDMX kickoff time) and a
        monospaced grid of what each player predicted for EACH game today."""
        embed = discord.Embed(
            title=f"⚽ Pronósticos de hoy ({day.isoformat()})",
            color=_color(settings.get("leaderboard_accent") or DEFAULT_ACCENT))
        if not matches:
            embed.description = "No hay partidos hoy."
        else:
            head_lines = []
            for m in matches:
                ka = m["kickoff_at"]
                if ka is not None and ka.tzinfo is None:
                    ka = ka.replace(tzinfo=timezone.utc)
                when = ka.astimezone(CDMX).strftime("%H:%M") if ka else "—"
                line = f"`#{m['id']}` **{m['home'] or '—'}** vs **{m['away'] or '—'}** · {when}"
                if m["finished"] and m["home_score"] is not None and m["away_score"] is not None:
                    line += f" · ✅ Final **{m['home_score']}–{m['away_score']}**"
                head_lines.append(line)
            head = "\n".join(head_lines)
            if not players:
                embed.description = head + "\n\nAún no hay pronósticos para hoy."
            else:
                cols = [f"{(m['home_code'] or '?')[:3]}-{(m['away_code'] or '?')[:3]}" for m in matches]
                header = (f"{'Jugador':<{self._NAME_W}} "
                          + " ".join(f"{c:>{self._PICK_W}}" for c in cols) + f" {'Pts':>4}")
                lines = [header, "─" * len(header)]
                # Result row: the real score per column, so each player's points
                # below are self-explanatory. Only shown once a game has finished.
                if any(m["finished"] and m["home_score"] is not None and m["away_score"] is not None
                       for m in matches):
                    res_cells = []
                    for m in matches:
                        if m["finished"] and m["home_score"] is not None and m["away_score"] is not None:
                            cell = f"{m['home_score']}-{m['away_score']}"
                        else:
                            cell = "—"
                        res_cells.append(f"{cell:>{self._PICK_W}}")
                    lines.append(f"{'Resultado':<{self._NAME_W}} " + " ".join(res_cells) + f" {'':>4}")
                    lines.append("─" * len(header))
                for p in players[:15]:
                    name = self._name(p).replace("`", "'").replace("\n", " ").strip()
                    if len(name) > self._NAME_W:
                        name = name[: self._NAME_W - 1] + "…"
                    cells = []
                    for m in matches:
                        pick = p["picks"].get(m["id"])
                        if pick is None:
                            cells.append(f"{'—':>{self._PICK_W}}")
                            continue
                        exact = (m["finished"] and m["home_score"] is not None and m["away_score"] is not None
                                 and pick[0] == m["home_score"] and pick[1] == m["away_score"])
                        cell = f"{pick[0]}-{pick[1]}" + ("*" if exact else "")
                        cells.append(f"{cell:>{self._PICK_W}}")
                    lines.append(f"{name:<{self._NAME_W}} " + " ".join(cells) + f" {p['points']:>4}")
                embed.description = head + "\n```\n" + "\n".join(lines) + "\n```"
        embed.set_footer(text="Pronóstico de cada jugador por partido · * = exacto · Solo partidos de hoy (CDMX) · Última actualización")
        embed.timestamp = datetime.now(timezone.utc)  # shown next to the footer; updates every refresh
        return embed

    async def _publish(self, guild_id, channel_id, settings: dict, embed: discord.Embed, mid_key: str):
        guild = self.bot.get_guild(int(guild_id))
        if guild is None:
            return None
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            return None
        mid = settings.get(mid_key)
        if mid:
            try:
                msg = await channel.fetch_message(int(mid))
                await msg.edit(embed=embed)
                await self._xadd(guild_id)
                return None
            except discord.NotFound:
                pass
            except discord.HTTPException:
                return None
        try:
            msg = await channel.send(embed=embed)
        except discord.HTTPException:
            return None
        await self._xadd(guild_id)
        return msg.id

    async def _xadd(self, guild_id):
        if not self.redis:
            return
        try:
            await self.redis.xadd(f"leaderboard:{guild_id}", {"data": json.dumps({"type": "update"})})
        except Exception:
            pass

    async def _publish_names(self, guild_id, rows: list[dict]):
        """Publish resolved guild display names to Redis so the web + Activity boards show
        the same names as Discord. Hash leaderboard:names:{guild_id} = {user_id: display}.
        Only users resolved from the member cache are written; the backend falls back to the
        stored username otherwise (and for the AI player)."""
        if not self.redis:
            return
        mapping = {str(r["user_id"]): r["display"] for r in rows if r.get("display")}
        if not mapping:
            return
        try:
            key = f"leaderboard:names:{guild_id}"
            await self.redis.hset(key, mapping=mapping)
            await self.redis.expire(key, 86400)
        except Exception:
            pass


def _color(hex_str: str) -> int:
    try:
        return int(str(hex_str).lstrip("#")[:6], 16)
    except Exception:
        return int(DEFAULT_ACCENT.lstrip("#"), 16)


async def setup(bot):
    await bot.add_cog(Leaderboard(bot))
