<div align="center">

# SportCrawl

<p>
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.12" />
  <img src="https://img.shields.io/badge/Typer-CLI-009688?style=flat-square&logo=python&logoColor=white" alt="Typer CLI" />
  <img src="https://img.shields.io/badge/JavaScript-Chrome_Extension-F7DF1E?style=flat-square&logo=javascript&logoColor=black" alt="JavaScript" />
  <img src="https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/SQLAlchemy-2.0_async-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white" alt="SQLAlchemy" />
  <img src="https://img.shields.io/badge/Pydantic-v2-E92063?style=flat-square&logo=pydantic&logoColor=white" alt="Pydantic v2" />
  <img src="https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker" />
  <img src="https://img.shields.io/badge/GitHub_Actions-CI%2FCD-2088FF?style=flat-square&logo=githubactions&logoColor=white" alt="GitHub Actions" />
  <img src="https://img.shields.io/badge/status-work_in_progress-orange?style=flat-square" alt="Work in Progress" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="MIT License" />
</p>

</div>

Async scraping infrastructure for football data from [fbref.com](https://fbref.com). SportCrawl extracts match, player, club, and competition statistics and persists them in PostgreSQL, with built-in anti-bot evasion via a real Chrome browser session.

The architecture follows hexagonal / domain-driven design with strict layer contracts enforced by import-linter. The scraping core, persistence layer, and domain scrapers are fully decoupled — adding a new data domain or a new sport requires no changes to shared infrastructure.

## Architecture

```
ports/           Abstract interfaces — BaseScraper, BaseRepository (no concrete deps)
core/            Shared kernel — logging, exceptions, generics
config/          Pydantic-settings environment configuration
infrastructure/  Adapters — PydollEngine (CDP), SQLAlchemy sessions, Alembic, job loop
domains/         Football domain scrapers, models, and repositories
cli/             Typer entry points
extensions/      Chrome extension — Cloudflare clearance capture + task fetch
```

The Python `work_server` is the orchestrator. The Chrome extension is a dumb HTTP client: it captures `cf_clearance` cookies from fbref.com and fetches URLs on demand. This inverted architecture is what makes Cloudflare Bot Management evasion reliable — a real, resident Chrome session rather than headless simulation.

## Current scope

**v0.7.0 — active development**

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Core abstractions, generics, structured logging | ✅ Complete |
| 2 | PydollEngine — async Chrome/CDP browser adapter | ✅ Complete |
| 3 | CLI (Typer), scraper port contracts | ✅ Complete |
| 4 | Provenance audit log — per-job run tracking | ✅ Complete |
| 5 | ScrapeQueue orchestration — concurrent job loop | 🔄 In progress |
| — | Football domain scrapers (player, club, competition, match) | 📋 Planned |

The project is designed from the start to support multiple sports. All sports share a single PostgreSQL instance partitioned by schema (`sch_infra` for the shared task queue, `sch_football` for football-specific tables, future schemas for other sports).

## Installation

**Prerequisites**

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- Docker (for PostgreSQL via Compose)
- Google Chrome (for the scraping extension)

**Setup**

```bash
git clone https://github.com/ChechiDev/sportcrawl.git
cd sportcrawl
uv sync
```

**Start the database**

```bash
docker compose up -d
uv run alembic upgrade head
```

**Run tests**

```bash
# Full suite (requires Docker for integration tests)
uv run pytest

# Unit tests only (no Docker required)
uv run pytest tests/unit/

# With coverage report
uv run pytest --cov=. --cov-fail-under=80
```

**Chrome extension**

1. Open `chrome://extensions` and enable **Developer mode**.
2. Click **Load unpacked** and select `extensions/sportcrawl-chrome/`.
3. Click the SportCrawl icon → set **Work server URL** and **Work server token** → Save.
