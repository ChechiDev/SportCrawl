"""Unit tests for JobLoop.drain().

Covers:
- drain() with empty queue returns 0 without calling _run_batch
- drain() processes all batches when queue has multiple pages
- drain() stops at batch boundary when stop_event is set
- drain() return value equals sum of processed rows across all batches

All dependencies are fully mocked. No real DB, no real browser.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from config.settings import ScrapingSettings
from infrastructure.jobs.job_loop import JobLoop

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides: Any) -> ScrapingSettings:
    base: dict[str, Any] = {
        "max_retries": 1,
        "base_delay": 0.0,
        "max_delay": 0.0,
        "request_timeout": 5,
        "max_concurrent_requests": 5,
        "max_queue_retries": 3,
    }
    base.update(overrides)
    return ScrapingSettings(**base)


def _make_session_factory() -> Any:
    """Return an async context manager factory yielding a mock session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    @asynccontextmanager
    async def _factory() -> AsyncIterator[Any]:
        yield session

    return _factory


def _build_job_loop_with_drain_mock(
    *,
    batch_results: list[int],
) -> tuple[JobLoop, list[int]]:
    """Build a JobLoop and patch _run_batch to return values from batch_results.

    The patch replaces _run_batch on the instance so we can verify call count
    and return values without touching _process internals.

    Returns:
        (loop, call_log) — call_log is a list that records each _run_batch
        return value in call order.
    """
    settings = _make_settings()
    loop = JobLoop(
        session_factory=_make_session_factory(),
        scraper_factory=MagicMock(),
        queue_repo_factory=MagicMock(),
        provenance_repo_factory=MagicMock(),
        provenance_factory=MagicMock(),
        settings=settings,
    )

    call_log: list[int] = []
    result_iter = iter(batch_results)

    async def _fake_run_batch(batch_size: int) -> int:
        try:
            val = next(result_iter)
        except StopIteration:
            val = 0
        call_log.append(val)
        return val

    loop._run_batch = _fake_run_batch  # type: ignore[method-assign]
    return loop, call_log


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDrainEmptyQueue:
    async def test_drain_empty_queue_returns_zero(self) -> None:
        """drain() returns 0 immediately when queue is empty on first batch."""
        loop, call_log = _build_job_loop_with_drain_mock(batch_results=[0])
        stop_event = asyncio.Event()

        result = await loop.drain(batch_size=10, stop_event=stop_event)

        assert result == 0

    async def test_drain_empty_queue_does_not_call_run_batch_again(self) -> None:
        """drain() does not call _run_batch a second time when first batch is empty."""
        loop, call_log = _build_job_loop_with_drain_mock(batch_results=[0])
        stop_event = asyncio.Event()

        await loop.drain(batch_size=10, stop_event=stop_event)

        # _run_batch was called exactly once (to discover the queue is empty)
        assert len(call_log) == 1


class TestDrainProcessesAllBatches:
    async def test_drain_processes_all_batches(self) -> None:
        """Queue with 15 jobs at batch_size=5 calls _run_batch 3 times."""
        # 3 batches of 5, then empty → _run_batch called 4 times total
        loop, call_log = _build_job_loop_with_drain_mock(
            batch_results=[5, 5, 5, 0]
        )
        stop_event = asyncio.Event()

        await loop.drain(batch_size=5, stop_event=stop_event)

        # 3 non-empty batches + 1 empty batch to detect end
        assert call_log.count(5) == 3

    async def test_drain_returns_total_processed(self) -> None:
        """drain() return value equals the sum of all _run_batch return values."""
        loop, call_log = _build_job_loop_with_drain_mock(
            batch_results=[5, 5, 5, 0]
        )
        stop_event = asyncio.Event()

        total = await loop.drain(batch_size=5, stop_event=stop_event)

        assert total == 15


class TestDrainStopEvent:
    async def test_drain_stop_event_halts_at_batch_boundary(self) -> None:
        """stop_event set before second batch causes drain to exit after first."""
        stop_event = asyncio.Event()
        call_count = 0

        settings = _make_settings()
        loop = JobLoop(
            session_factory=_make_session_factory(),
            scraper_factory=MagicMock(),
            queue_repo_factory=MagicMock(),
            provenance_repo_factory=MagicMock(),
            provenance_factory=MagicMock(),
            settings=settings,
        )

        async def _fake_run_batch(batch_size: int) -> int:
            nonlocal call_count
            call_count += 1
            # Set stop_event after the first batch so drain exits
            # at the top-of-loop check before the second call.
            stop_event.set()
            return 5

        loop._run_batch = _fake_run_batch  # type: ignore[method-assign]

        result = await loop.drain(batch_size=5, stop_event=stop_event)

        # Only one batch processed — stop_event was set during first batch
        assert call_count == 1
        assert result == 5

    async def test_drain_stop_event_set_before_call_returns_zero(self) -> None:
        """drain() returns 0 without calling _run_batch when stop_event is pre-set."""
        loop, call_log = _build_job_loop_with_drain_mock(batch_results=[5, 5, 0])
        stop_event = asyncio.Event()
        stop_event.set()  # pre-set before drain() is called

        result = await loop.drain(batch_size=5, stop_event=stop_event)

        assert result == 0
        assert len(call_log) == 0


class TestDrainReturnValue:
    async def test_drain_returns_total_across_mixed_batches(self) -> None:
        """drain() sums partial batches correctly."""
        # Simulate: batch of 3, batch of 7, batch of 2, then empty
        loop, call_log = _build_job_loop_with_drain_mock(
            batch_results=[3, 7, 2, 0]
        )
        stop_event = asyncio.Event()

        total = await loop.drain(batch_size=10, stop_event=stop_event)

        assert total == 12
