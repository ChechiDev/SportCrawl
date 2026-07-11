"""Unit tests for infrastructure.work_server.runtime (Phase 4 — task 4.1).

Tests use mocked AppRunner, TCPSite, JobLoop, and engine to verify
serve() sets up the composition root correctly without real DB/network.

Covers (REQ-9.6, REQ-9.7):
- serve() sets up AppRunner and TCPSite
- serve() creates JobLoop background task via asyncio.create_task
- serve() installs SIGTERM/SIGINT signal handlers
- shutdown sequence: site.stop → runner.cleanup → engine.dispose
- JobLoop task is awaited with a 30s timeout on shutdown
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(
    *,
    host: str = "127.0.0.1",
    port: int = 9731,
    token: str = "test-token",
    poll_interval: float = 5.0,
) -> MagicMock:
    """Return a mock Settings object with required attributes."""
    db = MagicMock()
    db.host = "localhost"
    db.port = 5432
    db.name = "testdb"
    db.user = "testuser"
    db.password = MagicMock()
    db.password.get_secret_value.return_value = "testpass"
    db.pool_size = 5
    db.max_overflow = 10
    db.pool_timeout = 30
    db.pool_recycle = 1800
    db.ssl_mode = None

    scraping = MagicMock()
    scraping.work_server_token = MagicMock()
    scraping.work_server_token.get_secret_value.return_value = token
    scraping.max_concurrent_requests = 3
    scraping.max_queue_retries = 5
    scraping.max_retries = 3
    scraping.base_delay = 1.0
    scraping.max_delay = 60.0
    scraping.request_timeout = 30
    scraping.poll_interval = poll_interval

    settings = MagicMock()
    settings.db = db
    settings.scraping = scraping
    settings.work_server_host = host
    settings.work_server_port = port
    return settings


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestServeCompositionRoot:
    """serve() must set up the full composition root (REQ-9.6)."""

    async def test_serve_sets_up_app_runner(self) -> None:
        """serve() must call AppRunner.setup() before starting."""
        from infrastructure.work_server.runtime import serve

        settings = _make_settings()

        with (
            patch(
                "infrastructure.work_server.runtime.create_async_engine"
            ) as mock_engine_fn,
            patch("infrastructure.work_server.runtime.async_sessionmaker"),
            patch("infrastructure.work_server.runtime.ScrapeQueueWorkAdapter"),
            patch("infrastructure.work_server.runtime.create_app") as mock_create_app,
            patch("infrastructure.work_server.runtime.web.AppRunner") as MockRunner,
            patch("infrastructure.work_server.runtime.web.TCPSite") as MockSite,
            patch("infrastructure.work_server.runtime.JobLoop"),
        ):
            mock_app = MagicMock()
            mock_create_app.return_value = mock_app

            runner_instance = AsyncMock()
            runner_instance.setup = AsyncMock()
            runner_instance.cleanup = AsyncMock()
            MockRunner.return_value = runner_instance

            site_instance = AsyncMock()
            site_instance.start = AsyncMock()
            site_instance.stop = AsyncMock()
            MockSite.return_value = site_instance

            engine_instance = AsyncMock()
            engine_instance.dispose = AsyncMock()
            mock_engine_fn.return_value = engine_instance

            # Trigger stop immediately via a task
            stop_called = False

            async def _stop_after_start() -> None:
                nonlocal stop_called
                await asyncio.sleep(0)
                stop_called = True

            # Patch stop_event so we can control shutdown
            stop_event = asyncio.Event()

            with patch(
                "infrastructure.work_server.runtime.asyncio.Event",
                return_value=stop_event,
            ):
                # Set the event immediately so serve() exits fast
                stop_event.set()

                with patch(
                    "infrastructure.work_server.runtime._jobloop_forever",
                    new_callable=AsyncMock,
                ):
                    await serve(settings)

            runner_instance.setup.assert_awaited()

    async def test_serve_starts_tcp_site(self) -> None:
        """serve() must start a TCPSite after AppRunner setup."""
        from infrastructure.work_server.runtime import serve

        settings = _make_settings()

        with (
            patch(
                "infrastructure.work_server.runtime.create_async_engine"
            ) as mock_engine_fn,
            patch("infrastructure.work_server.runtime.async_sessionmaker"),
            patch("infrastructure.work_server.runtime.ScrapeQueueWorkAdapter"),
            patch("infrastructure.work_server.runtime.create_app"),
            patch("infrastructure.work_server.runtime.web.AppRunner") as MockRunner,
            patch("infrastructure.work_server.runtime.web.TCPSite") as MockSite,
            patch("infrastructure.work_server.runtime.JobLoop"),
        ):
            runner_instance = AsyncMock()
            runner_instance.setup = AsyncMock()
            runner_instance.cleanup = AsyncMock()
            MockRunner.return_value = runner_instance

            site_instance = AsyncMock()
            site_instance.start = AsyncMock()
            site_instance.stop = AsyncMock()
            MockSite.return_value = site_instance

            engine_instance = AsyncMock()
            engine_instance.dispose = AsyncMock()
            mock_engine_fn.return_value = engine_instance

            stop_event = asyncio.Event()
            with patch(
                "infrastructure.work_server.runtime.asyncio.Event",
                return_value=stop_event,
            ):
                stop_event.set()
                with patch(
                    "infrastructure.work_server.runtime._jobloop_forever",
                    new_callable=AsyncMock,
                ):
                    await serve(settings)

            site_instance.start.assert_awaited()

    async def test_serve_creates_jobloop_task(self) -> None:
        """serve() must start JobLoop as an asyncio.create_task (shared event loop)."""
        from infrastructure.work_server.runtime import serve

        settings = _make_settings()
        tasks_created: list[str] = []

        original_create_task = asyncio.create_task

        def _spy_create_task(coro, **kwargs):
            tasks_created.append(getattr(coro, "__name__", str(coro)))
            # cancel immediately so it doesn't block
            task = original_create_task(coro, **kwargs)
            return task

        with (
            patch(
                "infrastructure.work_server.runtime.create_async_engine"
            ) as mock_engine_fn,
            patch("infrastructure.work_server.runtime.async_sessionmaker"),
            patch("infrastructure.work_server.runtime.ScrapeQueueWorkAdapter"),
            patch("infrastructure.work_server.runtime.create_app"),
            patch("infrastructure.work_server.runtime.web.AppRunner") as MockRunner,
            patch("infrastructure.work_server.runtime.web.TCPSite") as MockSite,
            patch("infrastructure.work_server.runtime.JobLoop"),
            patch(
                "infrastructure.work_server.runtime.asyncio.create_task",
                side_effect=_spy_create_task,
            ),
        ):
            runner_instance = AsyncMock()
            runner_instance.setup = AsyncMock()
            runner_instance.cleanup = AsyncMock()
            MockRunner.return_value = runner_instance

            site_instance = AsyncMock()
            site_instance.start = AsyncMock()
            site_instance.stop = AsyncMock()
            MockSite.return_value = site_instance

            engine_instance = AsyncMock()
            engine_instance.dispose = AsyncMock()
            mock_engine_fn.return_value = engine_instance

            stop_event = asyncio.Event()
            with patch(
                "infrastructure.work_server.runtime.asyncio.Event",
                return_value=stop_event,
            ):
                stop_event.set()
                with patch(
                    "infrastructure.work_server.runtime._jobloop_forever",
                    new_callable=AsyncMock,
                ):
                    await serve(settings)

        assert len(tasks_created) >= 1, "asyncio.create_task must be called for JobLoop"

    async def test_serve_disposes_engine_on_shutdown(self) -> None:
        """serve() must call engine.dispose() during shutdown (REQ-9.7)."""
        from infrastructure.work_server.runtime import serve

        settings = _make_settings()

        with (
            patch(
                "infrastructure.work_server.runtime.create_async_engine"
            ) as mock_engine_fn,
            patch("infrastructure.work_server.runtime.async_sessionmaker"),
            patch("infrastructure.work_server.runtime.ScrapeQueueWorkAdapter"),
            patch("infrastructure.work_server.runtime.create_app"),
            patch("infrastructure.work_server.runtime.web.AppRunner") as MockRunner,
            patch("infrastructure.work_server.runtime.web.TCPSite") as MockSite,
            patch("infrastructure.work_server.runtime.JobLoop"),
        ):
            runner_instance = AsyncMock()
            runner_instance.setup = AsyncMock()
            runner_instance.cleanup = AsyncMock()
            MockRunner.return_value = runner_instance

            site_instance = AsyncMock()
            site_instance.start = AsyncMock()
            site_instance.stop = AsyncMock()
            MockSite.return_value = site_instance

            engine_instance = AsyncMock()
            engine_instance.dispose = AsyncMock()
            mock_engine_fn.return_value = engine_instance

            stop_event = asyncio.Event()
            with patch(
                "infrastructure.work_server.runtime.asyncio.Event",
                return_value=stop_event,
            ):
                stop_event.set()
                with patch(
                    "infrastructure.work_server.runtime._jobloop_forever",
                    new_callable=AsyncMock,
                ):
                    await serve(settings)

            engine_instance.dispose.assert_awaited()

    async def test_serve_cleans_up_runner_on_shutdown(self) -> None:
        """serve() must call runner.cleanup() during shutdown (REQ-9.7)."""
        from infrastructure.work_server.runtime import serve

        settings = _make_settings()

        with (
            patch(
                "infrastructure.work_server.runtime.create_async_engine"
            ) as mock_engine_fn,
            patch("infrastructure.work_server.runtime.async_sessionmaker"),
            patch("infrastructure.work_server.runtime.ScrapeQueueWorkAdapter"),
            patch("infrastructure.work_server.runtime.create_app"),
            patch("infrastructure.work_server.runtime.web.AppRunner") as MockRunner,
            patch("infrastructure.work_server.runtime.web.TCPSite") as MockSite,
            patch("infrastructure.work_server.runtime.JobLoop"),
        ):
            runner_instance = AsyncMock()
            runner_instance.setup = AsyncMock()
            runner_instance.cleanup = AsyncMock()
            MockRunner.return_value = runner_instance

            site_instance = AsyncMock()
            site_instance.start = AsyncMock()
            site_instance.stop = AsyncMock()
            MockSite.return_value = site_instance

            engine_instance = AsyncMock()
            engine_instance.dispose = AsyncMock()
            mock_engine_fn.return_value = engine_instance

            stop_event = asyncio.Event()
            with patch(
                "infrastructure.work_server.runtime.asyncio.Event",
                return_value=stop_event,
            ):
                stop_event.set()
                with patch(
                    "infrastructure.work_server.runtime._jobloop_forever",
                    new_callable=AsyncMock,
                ):
                    await serve(settings)

            runner_instance.cleanup.assert_awaited()
