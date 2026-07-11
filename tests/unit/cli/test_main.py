"""Unit tests for cli.main (Phase 4 — task 4.4).

Verifies that:
- The work-server command is registered in the CLI
- Invoking the work-server command calls asyncio.run(serve(settings))

Uses unittest.mock to avoid real network or DB calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestWorkServerCommand:
    """The CLI must expose a 'work-server' command that wires to serve()."""

    def test_work_server_command_is_registered(self) -> None:
        """cli.main must expose a work_server function."""
        import cli.main as main_module

        assert hasattr(main_module, "work_server"), (
            "cli.main must define a work_server function"
        )

    def test_work_server_command_calls_asyncio_run(self) -> None:
        """Invoking work_server() must call asyncio.run with the serve coroutine."""
        from cli.main import work_server

        with (
            patch("cli.main.Settings") as MockSettings,
            patch("cli.main.asyncio.run") as mock_run,
            patch("cli.main.serve") as mock_serve,
        ):
            mock_serve.return_value = "fake-coro"
            work_server()

        # asyncio.run must have been called once
        mock_run.assert_called_once()
        # serve must have been called with the settings instance
        mock_serve.assert_called_once_with(MockSettings.return_value)

    def test_work_server_passes_settings_to_serve(self) -> None:
        """work_server() must build Settings() and pass it to serve()."""
        from cli.main import work_server

        settings_instance = MagicMock()

        with (
            patch("cli.main.Settings", return_value=settings_instance),
            patch("cli.main.asyncio.run"),
            patch("cli.main.serve") as mock_serve,
        ):
            mock_serve.return_value = "fake-coro"
            work_server()

        mock_serve.assert_called_once_with(settings_instance)
