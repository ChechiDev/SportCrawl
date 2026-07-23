## [0.18.1] - 2026-07-23

### Changed

- New root-level command: `uv run sportcrawl --all --workers N` replaces `players start` subcommand
- Unified Rich Live display: Teams, Players, and Player Info run in parallel in one display
- Teams workers now respect `--workers` count
- Country names shown in Teams worker labels instead of country codes
- Completed workers show `✓` symbol instead of `OK`
- Worker labels capitalize "Teams" and "Players"
- Seeding progress line no longer shows attempt counter
- Retry warnings use `` to be overwritten by success line
- Keyboard input suppressed during pipeline (only Ctrl+C exits)
- Separator `Rule` added between requirements and scraping sections
- FK-safe truncate order in `reset` command (child tables before parent)
- Preflight `check_seed_data` handles `club_teams` phase (checks countries, not players)
- `run_claim_loop` returns `int` in all workers (-1=restart, ≥0=processed count)
- Gender map pre-loaded once per browser session in `CountryTeamsWorker`
- `_parse_year` fixed for abbreviated seasons (e.g. "2023-24" → 2024)
- Named PK constraint `pk_tbl_teams` for upsert conflict target
- `_suppress_input`/`_restore_input` catch `termios.error | OSError | ValueError` instead of bare `Exception`
- BrowserException re-queue capped at 3 restarts per country
- `_do_reset` typed as `Console` (was `object`)
- `escape()` applied to dynamic values in all worker label assignments
- `*.log` added to `.gitignore`
- README Usage section rewritten for new command interface

### Files

- scripts/scrape_pipeline.py
- scripts/scrape_players.py
- scripts/scrape_player_info.py
- scripts/scrape_country_teams.py
- cli/main.py
- cli/players.py
- core/preflight/__init__.py
- core/preflight/checks.py
- core/application/base_worker.py
- infrastructure/scraping/country_teams.py
- infrastructure/persistence/repositories/teams.py
- tests/unit/application/test_base_worker.py
- .gitignore
- README.md

## v0.3.0 (2026-07-08)

### Feat

- **infra/work_server,cli**: add server and cli stubs
- **infra/browser**: add PydollEngine with lazy Chrome init and async context manager
- **infra/persistence**: add async session factory, ScrapeQueue model and Alembic migrations
- **infra/browser**: add ScrapingEngine ABC
- **core/base**: add base repository, scraper and service abstractions
- **config**: add settings with pydantic-settings and nested env support

### Fix

- **infra/migrations**: suppress Pyright reportUnusedImport on side-effect model import
- **infra**: narrow bare except Exception to specific exception types
- **infra/browser**: use *_ signature in __aexit__ to silence Pyright unused-param diagnostic
- **infra/browser**: resolve mypy --strict errors in PydollEngine
- **infra/persistence**: align url/domain to Text and fix deprecated op.get_bind in downgrade

## v0.2.0 (2026-07-07)

### Feat

- **core**: add types, logging and exception hierarchy

### Fix

- **core**: fix E501 line length violations in logging module
- **core**: add Literal types, log_level validation and strengthen test assertions
