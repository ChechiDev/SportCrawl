"""Unit tests for the smoke-player-info CLI command.

Tests cover:
- Command registration
- --dry-run mode (no DB, no scraper, exits 0)
- Secret masking (POSTGRES_PASSWORD never printed)
- smoke.env loading and POSTGRES_* → DB__* mapping
- Missing/incomplete smoke.env handling
- Option defaults and parsing
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()

_FAKE_ENV = "POSTGRES_DB=testdb\nPOSTGRES_USER=testuser\nPOSTGRES_PASSWORD=s3cr3t\n"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestCommandRegistration:
    def test_smoke_player_info_is_registered(self) -> None:
        names = [c.name for c in app.registered_commands]
        assert "smoke-player-info" in names, (
            "smoke-player-info must be registered in the Typer app"
        )


# ---------------------------------------------------------------------------
# --dry-run: no DB, no scraper, exits 0
# ---------------------------------------------------------------------------


class TestDryRun:
    def _dry_run(self, tmp_path: Path) -> object:
        env_file = tmp_path / "smoke.env"
        env_file.write_text(_FAKE_ENV)
        return runner.invoke(
            app, ["smoke-player-info", "--dry-run", "--smoke-env", str(env_file)]
        )

    def test_exits_zero(self, tmp_path: Path) -> None:
        result = self._dry_run(tmp_path)
        assert result.exit_code == 0, result.output

    def test_does_not_print_password(self, tmp_path: Path) -> None:
        result = self._dry_run(tmp_path)
        assert "s3cr3t" not in result.output

    def test_prints_db_name_not_password(self, tmp_path: Path) -> None:
        result = self._dry_run(tmp_path)
        assert "testdb" in result.output
        assert "s3cr3t" not in result.output

    def test_prints_candidate(self, tmp_path: Path) -> None:
        env_file = tmp_path / "smoke.env"
        env_file.write_text(_FAKE_ENV)
        result = runner.invoke(
            app,
            [
                "smoke-player-info",
                "--dry-run",
                "--smoke-env",
                str(env_file),
                "--candidate",
                "d70ce98e",
            ],
        )
        assert "d70ce98e" in result.output

    def test_prints_smoke_only_target(self, tmp_path: Path) -> None:
        result = self._dry_run(tmp_path)
        assert "127.0.0.1" in result.output

    def test_buffered_default_shown_as_true(self, tmp_path: Path) -> None:
        result = self._dry_run(tmp_path)
        assert "buffered  : True" in result.output

    def test_warm_pool_default_shown_as_false(self, tmp_path: Path) -> None:
        result = self._dry_run(tmp_path)
        assert "warm_pool : False" in result.output

    def test_workers_default_shown_as_two(self, tmp_path: Path) -> None:
        result = self._dry_run(tmp_path)
        assert "workers   : 2" in result.output

    def test_warm_pool_flag_reflected_in_output(self, tmp_path: Path) -> None:
        env_file = tmp_path / "smoke.env"
        env_file.write_text(_FAKE_ENV)
        result = runner.invoke(
            app,
            [
                "smoke-player-info",
                "--dry-run",
                "--warm-pool",
                "--smoke-env",
                str(env_file),
            ],
        )
        assert "warm_pool : True" in result.output


# ---------------------------------------------------------------------------
# Missing / broken smoke.env
# ---------------------------------------------------------------------------


class TestMissingEnv:
    def test_missing_file_exits_nonzero(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "smoke-player-info",
                "--smoke-env",
                str(tmp_path / "does_not_exist.env"),
            ],
        )
        assert result.exit_code != 0

    def test_missing_file_shows_blocked(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "smoke-player-info",
                "--smoke-env",
                str(tmp_path / "does_not_exist.env"),
            ],
        )
        assert "BLOCKED" in result.output

    def test_incomplete_env_exits_nonzero(self, tmp_path: Path) -> None:
        env_file = tmp_path / "smoke.env"
        env_file.write_text("POSTGRES_DB=onlydb\n")  # missing USER + PASSWORD
        result = runner.invoke(app, ["smoke-player-info", "--smoke-env", str(env_file)])
        assert result.exit_code != 0

    def test_incomplete_env_shows_blocked(self, tmp_path: Path) -> None:
        env_file = tmp_path / "smoke.env"
        env_file.write_text("POSTGRES_DB=onlydb\n")
        result = runner.invoke(app, ["smoke-player-info", "--smoke-env", str(env_file)])
        assert "BLOCKED" in result.output


# ---------------------------------------------------------------------------
# _load_smoke_env unit
# ---------------------------------------------------------------------------


class TestLoadSmokeEnv:
    def test_returns_dict_with_expected_keys(self, tmp_path: Path) -> None:
        from cli.smoke_player_info import _load_smoke_env

        env_file = tmp_path / "smoke.env"
        env_file.write_text(_FAKE_ENV)
        result = _load_smoke_env(env_file)
        assert result is not None
        assert result["POSTGRES_DB"] == "testdb"
        assert result["POSTGRES_USER"] == "testuser"

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        from cli.smoke_player_info import _load_smoke_env

        result = _load_smoke_env(tmp_path / "nope.env")
        assert result is None

    def test_returns_none_for_missing_keys(self, tmp_path: Path) -> None:
        from cli.smoke_player_info import _load_smoke_env

        env_file = tmp_path / "smoke.env"
        env_file.write_text("POSTGRES_DB=x\n")
        result = _load_smoke_env(env_file)
        assert result is None

    def test_ignores_comments_and_blank_lines(self, tmp_path: Path) -> None:
        from cli.smoke_player_info import _load_smoke_env

        content = "# comment\n\nPOSTGRES_DB=db\nPOSTGRES_USER=u\nPOSTGRES_PASSWORD=p\n"
        env_file = tmp_path / "smoke.env"
        env_file.write_text(content)
        result = _load_smoke_env(env_file)
        assert result is not None
        assert result["POSTGRES_DB"] == "db"


# ---------------------------------------------------------------------------
# _apply_env unit — isolated with patch.dict
# ---------------------------------------------------------------------------


class TestApplyEnv:
    def test_sets_db_host_to_smoke_target(self) -> None:
        from cli.smoke_player_info import _apply_env

        vals = {"POSTGRES_DB": "d", "POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p"}
        with patch.dict(os.environ, {}, clear=False):
            _apply_env(vals, buffered=True, warm_pool=False)
            assert os.environ["DB__HOST"] == "127.0.0.1"
            assert os.environ["DB__PORT"] == "15432"

    def test_maps_postgres_db_to_db_name(self) -> None:
        from cli.smoke_player_info import _apply_env

        vals = {
            "POSTGRES_DB": "mysmoke",
            "POSTGRES_USER": "u",
            "POSTGRES_PASSWORD": "p",
        }
        with patch.dict(os.environ, {}, clear=False):
            _apply_env(vals, buffered=True, warm_pool=False)
            assert os.environ["DB__NAME"] == "mysmoke"

    def test_buffer_enabled_when_buffered_true(self) -> None:
        from cli.smoke_player_info import _apply_env

        vals = {"POSTGRES_DB": "d", "POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p"}
        with patch.dict(os.environ, {}, clear=False):
            _apply_env(vals, buffered=True, warm_pool=False)
            assert os.environ["SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED"] == "true"

    def test_buffer_disabled_when_buffered_false(self) -> None:
        from cli.smoke_player_info import _apply_env

        vals = {"POSTGRES_DB": "d", "POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p"}
        with patch.dict(os.environ, {}, clear=False):
            _apply_env(vals, buffered=False, warm_pool=False)
            key = "SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED"
            assert os.environ[key] == "false"

    def test_warm_pool_enabled_only_when_both_flags_true(self) -> None:
        from cli.smoke_player_info import _apply_env

        vals = {"POSTGRES_DB": "d", "POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p"}
        with patch.dict(os.environ, {}, clear=False):
            _apply_env(vals, buffered=True, warm_pool=True)
            assert os.environ["SCRAPING__PLAYER_INFO_WARM_POOL_ENABLED"] == "true"

    def test_warm_pool_off_when_buffered_false(self) -> None:
        from cli.smoke_player_info import _apply_env

        vals = {"POSTGRES_DB": "d", "POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p"}
        with patch.dict(os.environ, {}, clear=False):
            _apply_env(vals, buffered=False, warm_pool=True)
            assert os.environ["SCRAPING__PLAYER_INFO_WARM_POOL_ENABLED"] == "false"

    def test_password_not_in_pgoptions(self) -> None:
        from cli.smoke_player_info import _apply_env

        vals = {
            "POSTGRES_DB": "d",
            "POSTGRES_USER": "u",
            "POSTGRES_PASSWORD": "topsecret99",
        }
        with patch.dict(os.environ, {}, clear=False):
            _apply_env(vals, buffered=True, warm_pool=False)
            pgopts = os.environ.get("PGOPTIONS", "")
            assert "topsecret99" not in pgopts

    def test_search_path_set_in_pgoptions(self) -> None:
        from cli.smoke_player_info import _apply_env

        vals = {"POSTGRES_DB": "d", "POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p"}
        with patch.dict(os.environ, {}, clear=False):
            _apply_env(vals, buffered=True, warm_pool=False)
            pgopts = os.environ.get("PGOPTIONS", "")
            assert "sch_fbref_infra" in pgopts
            assert "search_path" in pgopts
