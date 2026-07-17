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
            patch("cli.players.main_all", AsyncMock()),
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
            patch("cli.players.main_all", AsyncMock()),
        ):
            runner.invoke(players_app, ["--all", "--skip-preflight"])
        mock_run_checks.assert_not_called()

    def test_country_flag_calls_main_single(self):
        mock_main_single = AsyncMock()
        with (
            patch("cli.players.Settings", return_value=_make_settings()),
            patch(
                "cli.players.run_checks",
                AsyncMock(return_value=[_passing_result()]),
            ),
            patch("cli.players.main_single", mock_main_single),
        ):
            runner.invoke(players_app, ["--country", "ARG"])
        mock_main_single.assert_called_once()
        call_url = mock_main_single.call_args[0][0]
        assert "ARG" in call_url

    def test_all_flag_calls_main_all(self):
        mock_main_all = AsyncMock()
        with (
            patch("cli.players.Settings", return_value=_make_settings()),
            patch(
                "cli.players.run_checks",
                AsyncMock(return_value=[_passing_result()]),
            ),
            patch("cli.players.main_all", mock_main_all),
        ):
            runner.invoke(players_app, ["--all"])
        mock_main_all.assert_called_once()
