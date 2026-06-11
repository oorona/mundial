"""
Tests for backend/app/api/instrumentation.py

Covers:
  - _is_internal          — internal IPs, gateway header, external IPs
  - _range_cutoff         — 24h / 7d / 30d window computation
  - record_card_click     — CardUsage row written, Prometheus counter incremented
  - record_bot_command    — BotCommandMetrics row written, metrics updated
  - record_guild_event    — GuildEvent row written, JOIN/LEAVE counter branching
  - get_instrumentation_stats — aggregation queries executed, response shape
  - prometheus_metrics    — internal IP allowed, external IP blocked (403)
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.instrumentation import (
    _is_internal,
    _range_cutoff,
    record_card_click,
    record_bot_command,
    record_guild_event,
    get_instrumentation_stats,
    prometheus_metrics,
    purge_instrumentation_data,
    CardClickRequest,
    BotCommandRequest,
    GuildEventRequest,
)


# ── _is_internal ──────────────────────────────────────────────────────────────

class TestIsInternal:
    def _req(self, ip: str, gateway: bool = False):
        r = MagicMock()
        r.client = MagicMock()
        r.client.host = ip
        r.headers = MagicMock()
        r.headers.get = lambda k, d=None: "true" if (gateway and k == "X-Gateway-Request") else d
        return r

    def test_localhost_is_internal(self):
        assert _is_internal(self._req("127.0.0.1")) is True

    def test_docker_bridge_is_internal(self):
        assert _is_internal(self._req("172.18.0.5")) is True

    def test_192_168_is_internal(self):
        assert _is_internal(self._req("192.168.1.100")) is True

    def test_10_x_is_internal(self):
        assert _is_internal(self._req("10.0.0.1")) is True

    def test_public_ip_not_internal(self):
        assert _is_internal(self._req("8.8.8.8")) is False

    def test_gateway_header_makes_external_internal(self):
        assert _is_internal(self._req("8.8.8.8", gateway=True)) is True

    def test_no_client_not_internal(self):
        r = MagicMock()
        r.client = None
        r.headers = MagicMock()
        r.headers.get = lambda k, d=None: d
        assert _is_internal(r) is False


# ── _range_cutoff ─────────────────────────────────────────────────────────────

class TestRangeCutoff:
    def test_24h_cutoff(self):
        before = datetime.now(timezone.utc)
        cutoff = _range_cutoff("24h")
        after = datetime.now(timezone.utc)
        assert before - timedelta(hours=24, seconds=1) < cutoff < after - timedelta(hours=23)

    def test_7d_cutoff(self):
        cutoff = _range_cutoff("7d")
        expected = datetime.now(timezone.utc) - timedelta(hours=168)
        assert abs((cutoff - expected).total_seconds()) < 5

    def test_30d_cutoff(self):
        cutoff = _range_cutoff("30d")
        expected = datetime.now(timezone.utc) - timedelta(hours=720)
        assert abs((cutoff - expected).total_seconds()) < 5

    def test_unknown_range_defaults_to_7d(self):
        cutoff = _range_cutoff("bogus")
        expected = datetime.now(timezone.utc) - timedelta(hours=168)
        assert abs((cutoff - expected).total_seconds()) < 5


# ── record_card_click ─────────────────────────────────────────────────────────

class TestRecordCardClick:
    @pytest.mark.asyncio
    async def test_writes_card_usage_row(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch("app.api.instrumentation.card_views_total") as mock_counter:
            mock_counter.labels.return_value = MagicMock()
            await record_card_click(
                body=CardClickRequest(card_id="permissions", guild_id=1),
                db=db,
                current_user={"user_id": "42", "permission_level": "owner"},
            )

        db.add.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_increments_prometheus_counter(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch("app.api.instrumentation.card_views_total") as mock_counter:
            label_mock = MagicMock()
            mock_counter.labels.return_value = label_mock
            await record_card_click(
                body=CardClickRequest(card_id="audit-logs", guild_id=None),
                db=db,
                current_user={"user_id": "42", "permission_level": "admin"},
            )

        mock_counter.labels.assert_called_once_with(
            card_id="audit-logs", permission_level="admin"
        )
        label_mock.inc.assert_called_once()


# ── record_bot_command ────────────────────────────────────────────────────────

class TestRecordBotCommand:
    @pytest.mark.asyncio
    async def test_writes_metrics_row(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch("app.api.instrumentation.bot_commands_total") as mc, \
             patch("app.api.instrumentation.bot_command_duration_seconds") as md:
            mc.labels.return_value = MagicMock()
            md.labels.return_value = MagicMock()
            await record_bot_command(
                body=BotCommandRequest(
                    command="ping",
                    cog="General",
                    guild_id=1,
                    user_id=42,
                    duration_ms=12.5,
                    success=True,
                ),
                db=db,
            )

        db.add.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_observes_duration_histogram(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch("app.api.instrumentation.bot_commands_total") as mc, \
             patch("app.api.instrumentation.bot_command_duration_seconds") as md:
            mc.labels.return_value = MagicMock()
            hist_mock = MagicMock()
            md.labels.return_value = hist_mock

            await record_bot_command(
                body=BotCommandRequest(
                    command="help",
                    cog=None,
                    guild_id=None,
                    user_id=7,
                    duration_ms=250.0,
                    success=False,
                    error_type="CommandError",
                ),
                db=db,
            )

        hist_mock.observe.assert_called_once_with(0.25)


# ── record_guild_event ────────────────────────────────────────────────────────

class TestRecordGuildEvent:
    @pytest.mark.asyncio
    async def test_join_increments_counters(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch("app.api.instrumentation.guild_joins_total") as joins, \
             patch("app.api.instrumentation.guild_leaves_total") as leaves, \
             patch("app.api.instrumentation.guild_count") as count:
            await record_guild_event(
                body=GuildEventRequest(
                    guild_id=1, guild_name="Test", event_type="join", member_count=100
                ),
                db=db,
            )

        joins.inc.assert_called_once()
        count.inc.assert_called_once()
        leaves.inc.assert_not_called()

    @pytest.mark.asyncio
    async def test_leave_decrements_counter(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch("app.api.instrumentation.guild_joins_total") as joins, \
             patch("app.api.instrumentation.guild_leaves_total") as leaves, \
             patch("app.api.instrumentation.guild_count") as count:
            await record_guild_event(
                body=GuildEventRequest(
                    guild_id=1, guild_name="Test", event_type="LEAVE", member_count=99
                ),
                db=db,
            )

        leaves.inc.assert_called_once()
        count.dec.assert_called_once()
        joins.inc.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_type_normalised_to_uppercase(self):
        """'join' and 'JOIN' should both trigger the JOIN branch."""
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch("app.api.instrumentation.guild_joins_total") as joins, \
             patch("app.api.instrumentation.guild_leaves_total"), \
             patch("app.api.instrumentation.guild_count"):
            await record_guild_event(
                body=GuildEventRequest(
                    guild_id=1, guild_name="Test", event_type="join"
                ),
                db=db,
            )

        joins.inc.assert_called_once()


# ── get_instrumentation_stats ─────────────────────────────────────────────────

class TestGetInstrumentationStats:
    def _mock_db_with_empty_results(self):
        db = AsyncMock()
        empty_result = MagicMock()
        empty_result.all.return_value = []
        db.execute.return_value = empty_result
        return db

    @pytest.mark.asyncio
    async def test_returns_expected_shape(self):
        db = self._mock_db_with_empty_results()

        result = await get_instrumentation_stats(
            range="7d",
            guild_id=None,
            db=db,
            _admin={"user_id": "1"},
        )

        assert "guild_growth" in result
        assert "card_usage" in result
        assert "top_commands" in result
        assert "endpoint_perf" in result
        assert result["range"] == "7d"

    @pytest.mark.asyncio
    async def test_guild_id_filter_applied(self):
        db = self._mock_db_with_empty_results()

        await get_instrumentation_stats(
            range="24h",
            guild_id=42,
            db=db,
            _admin={"user_id": "1"},
        )

        # db.execute should be called for each sub-query
        assert db.execute.call_count >= 4

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_lists(self):
        db = self._mock_db_with_empty_results()

        result = await get_instrumentation_stats(
            range="30d",
            guild_id=None,
            db=db,
            _admin={"user_id": "1"},
        )

        assert result["guild_growth"] == []
        assert result["card_usage"] == []
        assert result["top_commands"] == []
        assert result["endpoint_perf"] == []


# ── prometheus_metrics ────────────────────────────────────────────────────────

class TestPrometheusMetrics:
    def _req(self, ip: str, gateway: bool = False):
        r = MagicMock()
        r.client = MagicMock()
        r.client.host = ip
        r.headers = MagicMock()
        r.headers.get = lambda k, d=None: "true" if (gateway and k == "X-Gateway-Request") else d
        return r

    @pytest.mark.asyncio
    async def test_internal_ip_returns_metrics(self):
        with patch("prometheus_client.generate_latest", return_value=b"# metrics"):
            result = await prometheus_metrics(request=self._req("127.0.0.1"))
            assert result.body == b"# metrics"

    @pytest.mark.asyncio
    async def test_external_ip_raises_403(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await prometheus_metrics(request=self._req("8.8.8.8"))

        assert exc.value.status_code == 403


# ── purge_instrumentation_data ────────────────────────────────────────────────

class TestPurgeInstrumentationData:
    """
    Tests for DELETE /instrumentation/data

    Covered:
      - 'all' tables purges every purgeable table
      - comma-separated table subset only deletes those tables
      - invalid table names are silently ignored (no valid tables → 400)
      - all-invalid tables param raises 400
      - older_than_days filter accepted
      - before / after date filters accepted
      - rowcount accumulated per table
    """

    def _mock_db(self, rowcount: int = 4):
        db = AsyncMock()
        db.commit = AsyncMock()
        result_mock = MagicMock()
        result_mock.rowcount = rowcount
        db.execute = AsyncMock(return_value=result_mock)
        return db

    @pytest.mark.asyncio
    async def test_purge_all_tables_calls_execute_for_each(self):
        db = self._mock_db(rowcount=2)

        result = await purge_instrumentation_data(
            older_than_days=None,
            before=None,
            after=None,
            tables="all",
            db=db,
            _admin={"user_id": "1"},
        )

        # Four purgeable tables → four DELETE executions
        assert db.execute.call_count == 4
        assert set(result["deleted"].keys()) == {"guild_events", "card_usage", "bot_commands", "request_metrics"}

    @pytest.mark.asyncio
    async def test_purge_subset_of_tables(self):
        db = self._mock_db(rowcount=3)

        result = await purge_instrumentation_data(
            older_than_days=None,
            before=None,
            after=None,
            tables="guild_events,card_usage",
            db=db,
            _admin={"user_id": "1"},
        )

        assert db.execute.call_count == 2
        assert "guild_events" in result["deleted"]
        assert "card_usage" in result["deleted"]
        assert "bot_commands" not in result["deleted"]

    @pytest.mark.asyncio
    async def test_all_invalid_table_names_raises_400(self):
        from fastapi import HTTPException
        db = self._mock_db()

        with pytest.raises(HTTPException) as exc:
            await purge_instrumentation_data(
                older_than_days=None,
                before=None,
                after=None,
                tables="nonexistent_table,also_bad",
                db=db,
                _admin={"user_id": "1"},
            )

        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_rowcount_aggregated_per_table(self):
        db = self._mock_db(rowcount=5)

        result = await purge_instrumentation_data(
            older_than_days=None,
            before=None,
            after=None,
            tables="guild_events",
            db=db,
            _admin={"user_id": "1"},
        )

        assert result["deleted"]["guild_events"] == 5

    @pytest.mark.asyncio
    async def test_older_than_days_accepted(self):
        db = self._mock_db(rowcount=10)

        result = await purge_instrumentation_data(
            older_than_days=7,
            before=None,
            after=None,
            tables="all",
            db=db,
            _admin={"user_id": "1"},
        )

        db.execute.assert_called()
        assert all(v == 10 for v in result["deleted"].values())

    @pytest.mark.asyncio
    async def test_date_range_filters_accepted(self):
        db = self._mock_db(rowcount=0)

        result = await purge_instrumentation_data(
            older_than_days=None,
            before="2025-06-01",
            after="2025-01-01",
            tables="bot_commands",
            db=db,
            _admin={"user_id": "1"},
        )

        assert result["deleted"]["bot_commands"] == 0
        db.commit.assert_called_once()
