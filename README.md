# fbrefly

fbrefly is a football data scraping infrastructure that extracts match, player, club, and competition data from public football statistics sites. The problem it solves is not the scraping itself but the plumbing around it: anti-bot evasion (Cloudflare), structured persistence, domain isolation, and reproducible local development — so that adding a new data domain never requires touching shared infrastructure code.

## Architecture

The project uses a domain-centric layout inspired by Screaming Architecture. The top-level folders tell you what the system *does*, not which framework it uses.

```
fbrefly/
  core/          Shared abstractions: generics, logging, exceptions
  config/        Pydantic-settings environment configuration
  infrastructure/  Browser engine (CDP via pydoll), database sessions, migrations
  domains/       One subfolder per data domain (player, club, competition, ...)
  cli/           Typer CLI entry points (Phase 3)
  chrome-extension/  Cloudflare bypass browser extension
  tests/         Mirrors the source tree
```

**core/** owns nothing domain-specific. It defines the TypeVars, logging setup, and exception hierarchies that every other layer depends on.

**core/base/** (introduced in Phase 2) holds generic base classes — `BaseRepository[T]`, `BaseScraper`, `BaseService` — that domains extend without modifying.

**infrastructure/** contains technology-specific implementations: the CDP browser engine (`PydollEngine` — concrete Chrome/CDP adapter wrapping pydoll-python), the async SQLAlchemy session factory, and Alembic migrations. It depends on `core/` but never on `domains/`.

**domains/** is the only place that knows about football concepts. Each domain extends core/base/ generics and wires them through infrastructure. No cross-domain imports.

See `.doc/` for per-folder design documentation.

## Running tests locally

```bash
uv run pytest
```

Tests are organized in two layers:

**Unit tests** (`tests/unit/`) test core abstractions and base classes with mocks. No database required.

**Integration tests** (`tests/integration/`) test ORM models and PostgreSQL-specific behavior (upsert semantics, native enums, constraints). These require Docker — `testcontainers` spins up a real PostgreSQL 16 container automatically. No manual database setup required.

```bash
# Unit tests only:
uv run pytest tests/unit/

# Integration tests only (Docker must be running):
uv run pytest tests/integration/

# All tests:
uv run pytest
```

Coverage gate is enforced at 80%. Run with coverage explicitly:

```bash
uv run pytest --cov=. --cov-fail-under=80
```

See `.doc/infrastructure/persistence.md` for the integration test architecture, known gotchas (asyncpg cross-loop, URL password masking, `create_all` vs Alembic), and how to add new integration tests.

## Adding a new domain

Create five files. Do not modify any existing file outside `domains/`.

```
domains/<name>/
  models.py       SQLAlchemy entity (extends DeclarativeBase)
  interfaces.py   Pydantic DTOs: RawData and DomainModel
  scraper.py      Extends BaseScraper — implements fetch() and parse()
  repository.py   Extends BaseRepository[YourEntity]
  service.py      Extends BaseService — orchestrates scraper + repository
```

That is the complete extension point. Core, infrastructure, and other domains stay untouched.

## Branch naming and commit format

Branches follow the pattern `<type>/<short-description>`:

```
feat/player-scraper
fix/rate-limit-retry
chore/update-deps
```

Commits use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(player): add scraper for FBref player pages
fix(repository): handle ON CONFLICT on upsert
chore: bump sqlalchemy to 2.0.40
```

Valid types: `feat`, `fix`, `refactor`, `perf`, `chore`, `test`, `docs`.

Versioning is automated via commitizen. `feat` bumps MINOR, `fix`/`refactor`/`perf` bump PATCH.

## Chrome Extension

The Chrome Extension (`extensions/fbrefly-chrome/`) is the scraping client of fbrefly, not merely a Cloudflare bypass tool. The architecture is inverted: the Python `work_server` is the orchestrator; the extension is a dumb HTTP client that fetches URLs on demand.

**Why a real Chrome browser instead of headless / httpx?**
Cloudflare Bot Management fingerprints TLS handshake, HTTP/2 SETTINGS frames, and browser APIs. A real Chrome session with a residential IP is the only reliable way to obtain a `cf_clearance` cookie that unlocks fbref.com without triggering JS challenges on every request.

### How to install

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked** and select `extensions/fbrefly-chrome/`.
4. Click the fbrefly icon → set **Work server URL** and **Work server token** → Save.

### What it does

- Listens for `cf_clearance` cookie changes on `fbref.com` via `chrome.cookies.onChanged`. When a new clearance is issued, it POSTs the value to `POST /api/clearance` on the `work_server`.
- Polls `GET /api/tasks/next` every ~60 seconds (minimum enforced by `chrome.alarms` in MV3). When a task arrives, it fetches the URL with `credentials: "include"` (so CF cookies are sent automatically), then POSTs the raw HTML to `POST /api/tasks/{id}/result`.
- Exponential backoff on 5xx/network errors. Fatal stop on 401/403 — the service worker records the stop in `chrome.storage.local` so it survives eviction and restarts.

See `.doc/chrome-extension.md` for the full API contract, design decisions, and production deployment notes.

## PostgreSQL schema layout

The project uses PostgreSQL schemas as the primary isolation boundary. All sports share one database instance — a constraint imposed by Oracle Cloud Free Tier (two Autonomous DB instances maximum; separate DBs per sport would exhaust the quota at sport #2).

| Schema | Contents | Who writes to it |
|---|---|---|
| `sch_infra` | Cross-sport infrastructure tables: `scrape_queue`, `scrapestatus` enum | `infrastructure/` layer |
| `sch_football` | Football domain tables: players, countries, clubs, competitions, matches | `domains/football/` |
| `sch_shared` _(future)_ | Truly shared domain entities across sports (e.g., `countries` if fbref reuses the same list) | TBD |
| `public` | `alembic_version` only | Alembic |

`alembic_version` stays in `public` intentionally: Alembic holds a live handle to that table during every migration run, so moving it into another schema mid-transaction causes a self-referential failure.

`scrape_queue` belongs in `sch_infra` — not `sch_football` — because it is a general-purpose task queue. Future sports (basketball, hockey) will submit URLs to the same queue without any schema changes to football tables.

Alembic autogenerate must see all schemas. Both `run_migrations_offline()` and `do_run_migrations()` in `infrastructure/persistence/migrations/env.py` pass `include_schemas=True` to `context.configure()`. Without it, Alembic ignores non-`public` objects and autogenerate produces empty migration files.

See `.doc/infrastructure/persistence-schema-strategy.md` for the full design decision: options evaluated, tradeoffs, and what goes where and why.

## Design documentation

`.doc/` contains per-folder design documentation: purpose, file-by-file breakdown, design decisions with alternatives considered, and extension guides. This folder is personal (Obsidian-based) and is excluded from git via `.gitignore`.
