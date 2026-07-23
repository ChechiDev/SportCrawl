"""Unit tests for cli.players."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from cli.players import players_app
from core.preflight.result import CheckResult

runner = CliRunner()


def _make_settings():
    db = MagicMock()
    db.user = "user"
    db.password = MagicMock()
    db.password.get_secret_value.return_value = "pass"
    db.host = "localhost"
    db.port = 5432
    db.name = "testdb"
    settings = MagicMock()
    settings.db = db
    return settings


def _passing_result(name="DB reachable"):
    return CheckResult(name=name, passed=True, detail="ok", fatal=True)


def _failing_result(name="DB reachable"):
    return CheckResult(
        name=name, passed=False, detail="Cannot connect", fatal=True
    )


class TestPlayersStart:
    def test_all_checks_pass_proceeds(self):
        with (
            patch("cli.players.Settings", return_value=_make_settings()),
            patch(
                "cli.players.run_checks",
                AsyncMock(return_value=[_passing_result()]),
            ),
            patch("scripts.scrape_pipeline.main", AsyncMock()),
        ):
            result = runner.invoke(players_app, ["--all"])
        assert result.exit_code == 0

    def test_fatal_check_fail_exits_1(self):
        with (
            patch("cli.players.Settings", return_value=_make_settings()),
            patch(
                "cli.players.run_checks",
                AsyncMock(return_value=[_failing_result()]),
            ),
        ):
            result = runner.invoke(players_app, ["--all"])
        assert result.exit_code == 1

    def test_skip_preflight_skips_run_checks(self):
        mock_run_checks = AsyncMock(return_value=[])
        with (
            patch("cli.players.Settings", return_value=_make_settings()),
            patch("cli.players.run_checks", mock_run_checks),
            patch("scripts.scrape_pipeline.main", AsyncMock()),
        ):
            runner.invoke(players_app, ["--all", "--skip-preflight"])
        mock_run_checks.assert_not_called()

    def test_country_flag_calls_pipeline(self):
        mock_pipeline = AsyncMock()
        with (
            patch("cli.players.Settings", return_value=_make_settings()),
            patch(
                "cli.players.run_checks",
                AsyncMock(return_value=[_passing_result()]),
            ),
            patch("scripts.scrape_pipeline.main", mock_pipeline),
        ):
            runner.invoke(players_app, ["--country", "ARG"])
        mock_pipeline.assert_called_once()
        _, kwargs = mock_pipeline.call_args
        assert kwargs.get("with_teams") is True

    def test_all_flag_calls_pipeline(self):
        mock_pipeline = AsyncMock()
        with (
            patch("cli.players.Settings", return_value=_make_settings()),
            patch(
                "cli.players.run_checks",
                AsyncMock(return_value=[_passing_result()]),
            ),
            patch("scripts.scrape_pipeline.main", mock_pipeline),
        ):
            runner.invoke(players_app, ["--all"])
        mock_pipeline.assert_called_once()

    def test_workers_flag_forwarded_to_pipeline(self):
        """--workers N must be forwarded as workers=N to pipeline main (FR-8)."""
        mock_pipeline = AsyncMock()
        with (
            patch("cli.players.Settings", return_value=_make_settings()),
            patch(
                "cli.players.run_checks",
                AsyncMock(return_value=[_passing_result()]),
            ),
            patch("scripts.scrape_pipeline.main", mock_pipeline),
        ):
            runner.invoke(players_app, ["--all", "--workers", "4"])
        mock_pipeline.assert_called_once()
        _, kwargs = mock_pipeline.call_args
        assert kwargs.get("workers") == 4

    def test_default_workers_is_one(self):
        """Omitting --workers must call pipeline main with workers=1."""
        mock_pipeline = AsyncMock()
        with (
            patch("cli.players.Settings", return_value=_make_settings()),
            patch(
                "cli.players.run_checks",
                AsyncMock(return_value=[_passing_result()]),
            ),
            patch("scripts.scrape_pipeline.main", mock_pipeline),
        ):
            runner.invoke(players_app, ["--all"])
        mock_pipeline.assert_called_once()
        _, kwargs = mock_pipeline.call_args
        assert kwargs.get("workers") == 1
