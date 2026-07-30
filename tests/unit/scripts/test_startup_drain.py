"""Unit tests for _startup_drain termination and batch_size parameter.

asyncio_mode = "auto" via pyproject.toml — no explicit @pytest.mark.asyncio.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from scripts.scrape_player_info import _startup_drain


def _make_session_factory(execute_results: list[list[int]]) -> MagicMock:
    """Return a session factory that yields execute results in order.

    Each element of execute_results is a list of fake row IDs returned
    by RETURNING scrape_queue.id in a single batch call.
    """
    call_index = 0

    async def _execute(_stmt: object, _params: dict[str, int]) -> MagicMock:
        nonlocal call_index
        result = MagicMock()
        rows = execute_results[call_index] if call_index < len(execute_results) else []
        result.fetchall.return_value = rows
        call_index += 1
        return result

    session = AsyncMock()
    session.execute.side_effect = _execute
    session.commit = AsyncMock()

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = cm
    return factory


class TestStartupDrainTermination:
    async def test_terminates_immediately_when_no_due_rows(self) -> None:
        """_startup_drain must return 0 and stop after first empty batch."""
        factory = _make_session_factory([[]])  # first call returns 0 rows

        with patch("scripts.scrape_player_info.get_session") as mock_gs:
            session = AsyncMock()
            result = MagicMock()
            result.fetchall.return_value = []
            session.execute.return_value = result
            session.commit = AsyncMock()
            mock_gs.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=session),
                __aexit__=AsyncMock(return_value=False),
            )

            total = await _startup_drain(factory, batch_size=200)

        assert total == 0

    async def test_accumulates_across_batches(self) -> None:
        """_startup_drain must continue batching until a 0-row result terminates it."""
        # Simulate: batch 1 = 200 rows, batch 2 = 150 rows, batch 3 = 0 rows (done)
        execute_results = [
            list(range(200)),   # batch 1
            list(range(150)),   # batch 2
            [],                 # terminator
        ]
        call_index = 0

        async def _execute(_stmt: object, _params: object) -> MagicMock:
            nonlocal call_index
            result = MagicMock()
            idx = call_index
            rows = execute_results[idx] if idx < len(execute_results) else []
            result.fetchall.return_value = rows
            call_index += 1
            return result

        session = AsyncMock()
        session.execute.side_effect = _execute
        session.commit = AsyncMock()

        with patch("scripts.scrape_player_info.get_session") as mock_gs:
            mock_gs.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=session),
                __aexit__=AsyncMock(return_value=False),
            )
            total = await _startup_drain(MagicMock(), batch_size=200)

        assert total == 350  # 200 + 150

    async def test_passes_batch_size_to_sql(self) -> None:
        """_startup_drain must pass :batch_size to the SQL statement."""
        captured_params: list[dict[str, int]] = []

        async def _execute(_stmt: object, params: dict[str, int]) -> MagicMock:
            captured_params.append(params)
            result = MagicMock()
            result.fetchall.return_value = []
            return result

        session = AsyncMock()
        session.execute.side_effect = _execute
        session.commit = AsyncMock()

        with patch("scripts.scrape_player_info.get_session") as mock_gs:
            mock_gs.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=session),
                __aexit__=AsyncMock(return_value=False),
            )
            await _startup_drain(MagicMock(), batch_size=42)

        assert len(captured_params) == 1
        assert captured_params[0]["batch_size"] == 42

    async def test_no_infinite_loop_when_first_batch_empty(self) -> None:
        """_startup_drain must not re-enter the loop after a zero result."""
        execute_call_count = 0

        async def _execute(_stmt: object, _params: object) -> MagicMock:
            nonlocal execute_call_count
            execute_call_count += 1
            result = MagicMock()
            result.fetchall.return_value = []
            return result

        session = AsyncMock()
        session.execute.side_effect = _execute
        session.commit = AsyncMock()

        with patch("scripts.scrape_player_info.get_session") as mock_gs:
            mock_gs.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=session),
                __aexit__=AsyncMock(return_value=False),
            )
            await _startup_drain(MagicMock(), batch_size=200)

        assert execute_call_count == 1
