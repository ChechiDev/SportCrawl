"""Unit tests for BackendUrlRepository lifecycle methods.

Tests mark_scraped ACTIVE transition, fetch_due_rows PENDING+ACTIVE inclusion,
and recover_stale_url STALE→PENDING reset.

asyncio_mode = "auto" via pyproject.toml — no explicit @pytest.mark.asyncio.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from infrastructure.persistence.repositories.backend_urls import (
    BackendUrlRepository,
)


def _make_session() -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = []
    session.execute.return_value = result
    return session


class TestMarkScrapedSetsActive:
    async def test_mark_scraped_sets_status_active(self) -> None:
        """mark_scraped must include status = 'ACTIVE' in the UPDATE statement."""
        session = _make_session()
        repo = BackendUrlRepository(session)
        await repo.mark_scraped("tbl_player_urls", 42)

        assert session.execute.call_count == 1
        call_args = session.execute.call_args
        # First positional arg is the sa.text statement
        stmt = call_args[0][0]
        sql = str(stmt)
        assert "status = 'ACTIVE'" in sql

    async def test_mark_scraped_passes_correct_row_id(self) -> None:
        """mark_scraped must bind :row_id to the provided row_id."""
        session = _make_session()
        repo = BackendUrlRepository(session)
        await repo.mark_scraped("tbl_player_urls", 99)

        call_args = session.execute.call_args
        params = call_args[0][1]
        assert params["row_id"] == 99

    async def test_mark_scraped_raises_on_unknown_table(self) -> None:
        """mark_scraped must raise ValueError for unknown tables."""
        import pytest

        session = _make_session()
        repo = BackendUrlRepository(session)
        with pytest.raises(ValueError, match="Unknown backend URL table"):
            await repo.mark_scraped("tbl_unknown", 1)


class TestFetchDueRowsIncludesPendingAndActive:
    async def test_fetch_due_rows_queries_pending_and_active(self) -> None:
        """fetch_due_rows must filter status IN ('PENDING', 'ACTIVE')."""
        session = _make_session()
        repo = BackendUrlRepository(session)
        await repo.fetch_due_rows("tbl_player_urls")

        assert session.execute.call_count == 1
        stmt = session.execute.call_args[0][0]
        sql = str(stmt)
        assert "IN ('PENDING', 'ACTIVE')" in sql

    async def test_fetch_due_rows_does_not_filter_single_status(self) -> None:
        """fetch_due_rows must NOT use a single-value status = '...' filter."""
        session = _make_session()
        repo = BackendUrlRepository(session)
        await repo.fetch_due_rows("tbl_player_urls")

        stmt = session.execute.call_args[0][0]
        sql = str(stmt)
        assert "status = 'PENDING'" not in sql
        assert "status = 'ACTIVE'" not in sql

    async def test_fetch_due_rows_raises_on_unknown_table(self) -> None:
        """fetch_due_rows must raise ValueError for unknown table names."""
        import pytest

        session = _make_session()
        repo = BackendUrlRepository(session)
        with pytest.raises(ValueError, match="Unknown backend URL table"):
            await repo.fetch_due_rows("tbl_invalid")


class TestRecoverStaleUrl:
    async def test_recover_stale_url_resets_stale_row(self) -> None:
        """recover_stale_url must UPDATE with PENDING status WHERE status = 'STALE'."""
        session = _make_session()
        repo = BackendUrlRepository(session)
        await repo.recover_stale_url("tbl_player_urls", 7)

        assert session.execute.call_count == 1
        stmt = session.execute.call_args[0][0]
        sql = str(stmt)
        assert "status     = 'PENDING'" in sql
        assert "status = 'STALE'" in sql

    async def test_recover_stale_url_binds_row_id(self) -> None:
        """recover_stale_url must bind :row_id to the provided id."""
        session = _make_session()
        repo = BackendUrlRepository(session)
        await repo.recover_stale_url("tbl_player_urls", 123)

        params = session.execute.call_args[0][1]
        assert params["row_id"] == 123

    async def test_recover_stale_url_raises_on_unknown_table(self) -> None:
        """recover_stale_url must raise ValueError for unknown tables."""
        import pytest

        session = _make_session()
        repo = BackendUrlRepository(session)
        with pytest.raises(ValueError, match="Unknown backend URL table"):
            await repo.recover_stale_url("tbl_unknown", 1)

    async def test_recover_stale_url_clears_error_metadata(self) -> None:
        """recover_stale_url must reset retry_count and clear last_error."""
        session = _make_session()
        repo = BackendUrlRepository(session)
        await repo.recover_stale_url("tbl_player_urls", 5)

        stmt = session.execute.call_args[0][0]
        sql = str(stmt)
        assert "retry_count = 0" in sql
        assert "last_error  = NULL" in sql
