# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.27.0] — 2026-08-25

### Added
- `smoke-clearance --real-clearance`: guarded CLI path; blocked at `provider_readiness` gate until all real providers are configured — no smoke execution performed
- `cli/smoke_clearance_real.py`: 15-gate real clearance harness scaffold — Protocol-only interfaces, injectable providers and seams, always-runs cleanup in `finally` block
- 71 unit tests covering all 15 gate paths, `check_expires_at` bounds (both exclusive), redaction self-test, and cleanup-on-startup-failure invariant
- E2E validation of `player_info` buffered dispatch and warm-pool execution paths complete (Phases A0–J3): direct mode, buffered mode, and buffered+warm-pool mode validated against an isolated smoke environment
- Architecture decision: buffered dispatch model generalized as a shared always-active dispatch runtime; `player_info` is the reference implementation for future workloads
- `docs/architecture/buffered-dispatch-engine.md`: architecture decision record for the buffered dispatch engine

### Fixed
- CI lint: ruff E501/E302/I001/UP017, flake8 E301 across harness and test files
- CI security: `pip` upgraded from `26.1.2` to `26.2.1` (resolves PYSEC-2026-3721)

### Notes
- Real smoke was NOT executed; `--real-clearance` remains blocked at `provider_readiness`
- CP-SMOKE-B provider implementations are NOT included in this release
- CP2/session-clearance-pool is out of scope and untouched

## [0.26.0] — 2026-07-30

### Changed
- `sch_fbref_backend` is now the sole source of truth for scraping URLs — redundant URL columns dropped from all domain tables (`tbl_countries.country_url`, `tbl_players.player_url`, `tbl_country_squads.clubs_url`, `tbl_competition.comp_url`)
- Daemon (`CadenceScheduler` + `PgNotifyListener`) removed from inline pipeline; must run as standalone `run_daemon.py`; direct INSERT used instead for immediate queue seeding
- `scrape_queue` pool size reduced from `workers×8` to `workers×4`
- Competitions preflight now skips re-scrape if already seeded
- `CooldownRequired` now scoped to scraping failures only (not DB errors)
- Work server URL scheme restricted to `https://` only (SSRF hardening)
- Chrome keepalive loop replaced with lightweight CDP `execute_script` ping instead of full DOM serialization

### Added
- Migrations p47a–p55a: drop URL columns, add indexes, fix `fn_notify_all_due` status filter, covering index for stale recovery
- `fk_country` propagated into `scrape_queue` rows at seed time for team_list jobs
- ON CONFLICT DO UPDATE in all queue seed INSERTs

### Fixed
- `BackendUrlRepository.fetch_due_rows`: was filtering on `status='ACTIVE'` (never matched); corrected to `status='PENDING'`
- S3 worker double URL prefix: `engine.navigate()` was prepending `_fbref_base_url` to an already-absolute URL
- Stats repos (`player_std_stats`, `player_shooting_stats`, `player_playing_time_stats`, `player_misc_stats`): FK violation on unknown `comp_id` now gracefully skipped per row instead of failing the entire job
- Phantom `player_discovery` entries removed from `scrape_queue` (no consumer worker existed)
- `SecretStr` Pyright narrowing in `config/settings.py`

## [0.25.0] — 2026-07-28

### Added
- `sch_fbref_backend` schema: centralized URL registry with scheduling metadata for all 5 entity types (players, teams, competitions, countries, country squads)
- PostgreSQL LISTEN/NOTIFY pipeline: triggers emit `fbref_scrape_due` when rows are due, Python listener enqueues into `scrape_queue`
- `CadenceScheduler`: async loop calling `fn_notify_all_due()` every 60s with clean shutdown
- `PgNotifyListener`: semaphore-guarded NOTIFY consumer with poll fallback on startup and exponential backoff reconnect
- `scripts/run_daemon.py`: standalone daemon entry point for Oracle Free Tier deployment
- `BackendUrlRepository`: `fetch_due_rows`, `mark_scraped`, `mark_failed` with exponential retry logic
- `scripts/backfill_backend_urls.py`: idempotent backfill + silent `sync_preflight()` called automatically on pipeline start
- Co-insert pattern: domain repositories populate `sch_fbref_backend` URL tables in the same transaction
- Workers wire `mark_scraped` / `mark_failed` after every queue outcome

### Changed
- All URL columns unified to absolute URLs (`https://fbref.com/...`) across domain tables and backend tables
- Scrapers (competitions, countries, players) now store absolute URLs from source

### Fixed
- `scrape_queue.job_type` made NOT NULL with DEFAULT `'default'` to fix silent UNIQUE constraint bypass (NULL != NULL in PostgreSQL)

## [0.24.1] — 2026-07-28

### Added
- Competitions scraper: scrape FBRef /en/comps/ during preflight to populate tbl_competition (152 competitions)
- tbl_comp_type reference table with dynamic upsert (no hardcoded seed)
- Migration p37a: rename PostgreSQL schemas to include fbref namespace prefix

### Changed
- Schema names: sch_shared→sch_fbref_shared, sch_football→sch_fbref_football, sch_infra→sch_fbref_infra across all application code
- fk_gender in tbl_competition now references tbl_gender.id (integer FK) instead of varchar
- flag_id values stored in UPPERCASE across tbl_flags, tbl_country_squads, tbl_competition
- reset command now drops all schemas before rebuilding from scratch
- Pipeline display labels updated: "Scraping All Teams by Country", "Scraping All Players by Country", "Scraping Player Profile & Stats"
- Worker retry display: WARNING (yellow) — Retrying (N/M) — entity name

### Fixed
- TeamsRepository: SELECT-only on tbl_competition (no longer writes to it)
- fk_flag resolved via tbl_flags.fk_country lookup when not present in HTML

## [0.23.0] — 2026-07-26

### Added
- `player_url` in `tbl_players` now stores the `/all_comps/` FBRef URL, enabling competition-level stats scraping without re-scraping

### Changed
- `tbl_teams.updated_at` — removed client-side `onupdate=func.now()`; upsert repo already sets it explicitly server-side

### Fixed
- `tbl_flags.flag_id` and `tbl_country_squads.fk_flag` ORM type corrected from `String(2)` to `String(3)` to match DB after migration `p24a`
- Dropped redundant `ix_player_queue_ref_queue_id` index (already covered by unique constraint) — migration `p27a`
- `p26a` downgrade now restores `player_info_url` as `nullable=True` instead of filling existing rows with empty strings

### Removed
- `player_info_url` column from `tbl_player_info` — redundant, URL already stored in `tbl_players.player_url` — migration `p26a`

## [0.22.1] — 2026-07-26

### Fixed
- `PlayerListScraper` now raises `PageLoadError` when 0 players are parsed and no "N Players" count header is present — CF challenge pages no longer get marked as DONE; jobs requeue automatically via the never-die policy
- `CountryPlayersScraper` maps FBRef country code `EIR` (Ireland) to `IRL` (Republic of Ireland) via `_COUNTRY_ID_ALIASES`
- `upsert_players_url` no-match log downgraded from WARNING to DEBUG for historical/micro-nation countries not present in the DB

### Changed
- README: CLI section updated to `start` subcommand with `-a`/`-c`/`-w` shorthands; logo width increased to 1024

## [0.20.0] — 2026-07-25

### Added
- Persistent DB-backed scrape queue for Teams scraping (`job_type='team_list'`, `scrape_queue` table)
- `SELECT FOR UPDATE SKIP LOCKED` for safe multi-worker concurrent access
- Resume-on-restart: interrupted jobs are picked up automatically on next run
- `--country` filter now propagates correctly into queue population for the Teams pipeline
- Auto-scaling worker count based on actual queue size at startup

## [0.19.0] — 2026-07-25

### Fixed
- `--country` filter ignored by the Teams scraper pipeline
- Worker count not auto-scaled when `--country` reduced the effective job set

## [0.18.1] — 2026-07-24

### Changed
- New root-level command: `uv run sportcrawl --all --workers N` replaces `players start` subcommand
- Unified Rich Live display: Teams, Players, and Player Info run in parallel in one display
- Teams workers now respect `--workers` count
- Country names shown in Teams worker labels instead of country codes
- Completed workers show `✓` symbol; worker labels capitalised consistently
- Keyboard input suppressed during pipeline run (only Ctrl+C exits)

### Fixed
- FK-safe truncate order in `reset` command (child tables before parent)
- `_parse_year` fixed for abbreviated seasons (e.g. `"2023-24"` → `2024`)
- Named PK constraint `pk_tbl_teams` for upsert conflict target
- BrowserException re-queue capped at 3 restarts per country
- `escape()` applied to all dynamic values in worker label assignments

## [0.18.0] — 2026-07-23

### Added
- Team discovery pipeline: domain model, ORM (`tbl_teams`, `tbl_competition`), Alembic migration `p16b`, scraper, and repository
- Auto-apply Alembic migrations on startup as a preflight step
- Teams scraper runs as an independent OS subprocess in parallel with the Players pipeline

### Fixed
- Post-upgrade preflight check now replaces (not appends) the failed revision result after auto-upgrade
- Lint and type errors across CI (ruff E501/E402, mypy suppressions, architecture contract)

## [0.17.0] — 2026-07-20

### Added
- Club discovery: `tbl_country_squads` domain model, ORM, Alembic migration `p16a`, batch upsert repository
- Country squads scraper with preflight auto-seeding of countries
- Professional CLI with Rich header, preflight check display, and display polish
- `BaseWorker` ABC with Template Method pattern — shared scraping lifecycle for all worker types
- TTL notification buffer in worker labels: warnings vanish after 5 seconds
- Inline bold red/orange status colors for worker label states

### Fixed
- Preflight country squads check now runs even when the seed check fails
- Preflight marks only the seed check resolved after seeding (not all checks)
- CDP keepalive, buffer logging, and Cloudflare tuning for worker stability
- Various lint/type errors (E741, E501, mypy strict)

## [0.16.0] — 2026-07-15

### Added
- Player info scraping supporting ~223k requests with concurrent workers and retry resilience
- New player fields: `citizenship`, `youth_nat_team`, `club`

## [0.15.0] — 2026-07-10

### Added
- Player info feature (initial implementation)

## [0.8.0] — 2026-07-09

### Added
- Players scraping pipeline foundation (concurrent player list scraping)

## [0.3.0] — 2026-07-08

### Added
- `PydollEngine` browser with lazy Chrome init and async context manager
- Async session factory, `ScrapeQueue` ORM model, and Alembic migrations
- `ScrapingEngine` ABC, base repository, scraper, and service abstractions
- Settings with `pydantic-settings` and nested env support

## [0.2.0] — 2026-07-07

### Added
- Core types, logging, and exception hierarchy

[Unreleased]: https://github.com/ChechiDev/sportcrawl/compare/v0.27.0...HEAD
[0.27.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.26.0...v0.27.0
[0.24.1]: https://github.com/ChechiDev/sportcrawl/compare/v0.23.0...v0.24.1
[0.23.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.20.0...v0.23.0
[0.20.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.18.1...v0.19.0
[0.18.1]: https://github.com/ChechiDev/sportcrawl/compare/v0.18.0...v0.18.1
[0.18.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.8.0...v0.15.0
[0.8.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.3.0...v0.8.0
[0.3.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/ChechiDev/sportcrawl/releases/tag/v0.2.0
