# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.22.1] — 2026-07-26

### Fixed
- `PlayerListScraper` now raises `PageLoadError` when 0 players are parsed and no \"N Players\" count header is present — CF challenge pages no longer get marked as DONE; jobs requeue automatically via the never-die policy
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

[Unreleased]: https://github.com/ChechiDev/sportcrawl/compare/v0.20.0...HEAD
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
