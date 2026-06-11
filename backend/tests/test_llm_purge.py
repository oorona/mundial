"""
Tests for the purge endpoint in backend/app/api/llm.py

Covers DELETE /llm/usage:
  - No filter → deletes all LLMUsage and LLMUsageSummary rows
  - older_than_days filter applied to both tables
  - before / after date filters applied
  - rowcounts returned correctly
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.api.llm import purge_llm_usage


def _mock_db(usage_rowcount: int = 5, summary_rowcount: int = 2):
    """Return an AsyncSession mock with two execute results in sequence."""
    db = AsyncMock()
    db.commit = AsyncMock()

    usage_result = MagicMock()
    usage_result.rowcount = usage_rowcount

    summary_result = MagicMock()
    summary_result.rowcount = summary_rowcount

    db.execute = AsyncMock(side_effect=[usage_result, summary_result])
    return db


class TestPurgeLLMUsage:
    @pytest.mark.asyncio
    async def test_no_filter_deletes_all(self):
        db = _mock_db(usage_rowcount=10, summary_rowcount=3)

        result = await purge_llm_usage(
            older_than_days=None,
            before=None,
            after=None,
            db=db,
            admin={"user_id": "1"},
        )

        assert result == {"deleted": 10, "summaries_deleted": 3}
        assert db.execute.call_count == 2
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_older_than_days_accepted(self):
        db = _mock_db(usage_rowcount=4, summary_rowcount=1)

        result = await purge_llm_usage(
            older_than_days=30,
            before=None,
            after=None,
            db=db,
            admin={"user_id": "1"},
        )

        assert result["deleted"] == 4
        assert result["summaries_deleted"] == 1
        db.execute.assert_called()

    @pytest.mark.asyncio
    async def test_before_date_filter_accepted(self):
        db = _mock_db(usage_rowcount=2, summary_rowcount=0)

        result = await purge_llm_usage(
            older_than_days=None,
            before="2025-01-01",
            after=None,
            db=db,
            admin={"user_id": "1"},
        )

        assert result["deleted"] == 2
        assert result["summaries_deleted"] == 0

    @pytest.mark.asyncio
    async def test_after_date_filter_accepted(self):
        db = _mock_db(usage_rowcount=0, summary_rowcount=0)

        result = await purge_llm_usage(
            older_than_days=None,
            before=None,
            after="2026-01-01",
            db=db,
            admin={"user_id": "1"},
        )

        assert result == {"deleted": 0, "summaries_deleted": 0}

    @pytest.mark.asyncio
    async def test_date_range_filters_accepted(self):
        db = _mock_db(usage_rowcount=7, summary_rowcount=2)

        result = await purge_llm_usage(
            older_than_days=None,
            before="2025-06-01",
            after="2025-01-01",
            db=db,
            admin={"user_id": "1"},
        )

        assert result["deleted"] == 7
        assert result["summaries_deleted"] == 2
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_zero_rows_deleted(self):
        db = _mock_db(usage_rowcount=0, summary_rowcount=0)

        result = await purge_llm_usage(
            older_than_days=None,
            before=None,
            after=None,
            db=db,
            admin={"user_id": "1"},
        )

        assert result == {"deleted": 0, "summaries_deleted": 0}
