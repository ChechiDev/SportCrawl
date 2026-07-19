<div align="center">

<img src="https://raw.githubusercontent.com/ChechiDev/SportCrawl/main/assets/images/sportcrawl-logo-wip.png" alt="SportCrawl Logo" width="800" />

---

<p>
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.12" />
  <img src="https://img.shields.io/badge/Typer-CLI-009688?style=flat-square&logo=python&logoColor=white" alt="Typer CLI" />
  <img src="https://img.shields.io/badge/JavaScript-Chrome_Extension-F7DF1E?style=flat-square&logo=javascript&logoColor=black" alt="JavaScript" />
  <img src="https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/SQLAlchemy-2.0_async-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white" alt="SQLAlchemy" />
  <img src="https://img.shields.io/badge/Pydantic-v2-E92063?style=flat-square&logo=pydantic&logoColor=white" alt="Pydantic v2" />
  <img src="https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker" />
  <img src="https://img.shields.io/badge/GitHub_Actions-CI%2FCD-2088FF?style=flat-square&logo=githubactions&logoColor=white" alt="GitHub Actions" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="MIT License" />
</p>

</div>

---

# Description

SportCrawl is an async scraping infrastructure built to extract structured football data from [FBRef.com](https://fbref.com) and persist it in a relational PostgreSQL database, ready for analysis, reporting, or downstream consumption.

FBRef is the most complete public source of football statistics, but it has no API. All data lives behind Cloudflare Bot Management, which blocks conventional scrapers and headless browsers. SportCrawl solves this by using a **real, resident Chrome session** paired with a custom extension that captures Cloudflare clearance cookies and relays fetch requests, making the traffic indistinguishable from a normal user.

**What it scrapes:**

- Countries and confederations
- Player rosters per country (career span, positions)
- Individual player profiles (bio, nationality, physical data, career history)
- National team associations *(in progress)*
- Teams *(in progress)*
- Team stats *(in progress)*
- Player stats by league *(in progress)*

**What it solves:**

- Reliable Cloudflare bypass without rotating proxies or third-party services
- Idempotent, resumable scraping via a PostgreSQL job queue (`SELECT FOR UPDATE SKIP LOCKED`)
- Parallel workers with isolated Chrome profiles — no browser lock conflicts
- Clean separation between scraping logic, persistence, and orchestration — adding a new data domain requires no changes to shared infrastructure

---

# Installation

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — package manager
- Docker — for PostgreSQL via Compose
- Google Chrome — for the scraping engine
- *(Optional)* A PostgreSQL client — [pgAdmin](https://www.pgadmin.org/), [TablePlus](https://tableplus.com/), or `psql` to inspect the data

## Clone and install

```bash
git clone https://github.com/ChechiDev/SportCrawl.git
cd SportCrawl
uv sync
```

## Environment

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

**Start the database**

```bash
docker compose up -d
```

---

## Usage

SportCrawl is driven entirely from the CLI. All commands run a **preflight check** before scraping — verifying the database connection, schema version, and seed data. If anything is missing, it's fixed automatically before the scrape starts.

## Scrape countries

Fetches all countries and confederations from FBRef and seeds the database. This is required before scraping players.

```bash
uv run sportcrawl countries start
```

## Scrape players

Scrapes the player roster for one or more countries.

```bash
# Single country
uv run sportcrawl players start --country ESP

# Multiple countries
uv run sportcrawl players start --country ESP,ARG,BRA

# All 219 countries
uv run sportcrawl players start --all
```

Run with parallel workers to speed up scraping across multiple countries:

```bash
uv run sportcrawl players start --all --workers 5
```

| Flag | Description |
|---|---|
| `--country` | Comma-separated FBRef country codes (e.g. `ESP,ARG`) |
| `--all` | Scrape all players by countries available in the database |
| `--workers N` | Number of parallel workers (default: `1`) |
| `--skip-preflight` | Skip the preflight check |
| `--recover-stale` | Reset jobs stuck in `IN_PROGRESS` for over 1 hour |

> The scraper supports up to 25 parallel workers. For best results and to avoid rate limiting, **1–5 workers is recommended**.

## Scrape Single player info

Scrapes individual player profiles — bio, nationality, positions, and career history.

```bash
uv run sportcrawl players start --all --with-player-info --workers 5
```

The `--with-player-info` flag runs the player list scrape first, then automatically queues and scrapes all individual profiles in the same run.

> **Heads up:** scraping all players across all countries means hundreds of thousands of individual requests. This can take several hours depending on the number of workers and your network conditions. Plan accordingly.


<details>
<summary><h3>Scraping usage example</h3></summary>

### Scraping by country

```bash
❯ uv run sportcrawl players start --all --with-player-info --workers 5
Preflight — Checking requirements
  OK    DB reachable: Connected successfully.
  OK    Alembic initialized: alembic_version table found.
  OK    Alembic revision: DB at revision p14m (>= p11e).
  OK    Schemas exist: sch_infra and sch_shared found.
  OK    Tables exist: All 8 tables found for phase 'players'.
  FAIL  Seed data: No countries found. Seed data required for phase 'players'.

Step 1 — Scraping countries
  OK  Seed data: 219 countries found.
  OK  Stale queue: No stale jobs found.

  7/7 checks passed

Scraping Players and Single player info
Step 2 — Scraping Players
RUN  [Crawl-1] [12 | 62/219] DJI: 118 players  
RUN  [Crawl-2] [12 | 62/219] DEN: 2,358 players
RUN  [Crawl-3] [13 | 62/219] DOM: 306 players  
RUN  [Crawl-4] [13 | 62/219] DMA: 136 players  
RUN  [Crawl-5] [12 | 62/219] CIV: 878 players  

Step 3 — Scraping Single player info
RUN  [Crawl-1] [41 | 204/48755] Player Name
RUN  [Crawl-2] [42 | 204/48755] Player Name
RUN  [Crawl-3] [41 | 204/48755] Player Name
RUN  [Crawl-4] [39 | 204/48755] Player Name
RUN  [Crawl-5] [41 | 204/48755] Player Name
```

</details>

## Reset Database

Truncates all scraped data from the database. Useful for testing or starting fresh.

```bash
uv run sportcrawl reset
```

> This only clears scraped data (players, player info, flags, queue). It does not drop the schema or run a migration rollback.

<details>
<summary><h3>Reset database example</h3></summary>

```bash
❯ uv run sportcrawl reset    
╭──────────────────────────────────────────────────────────────────────── Reset Database ─────────────────────────────────────────────────────────────────────────╮
│ WARNING                                                                                                                                                         │
│                                                                                                                                                                 │
│ This will delete ALL scraped data:                                                                                                                              │
│   • sch_shared: countries, players, player_info, photos, positions                                                                                              │
│   • sch_infra: scrape_queue, player_discovery_batch, player_queue_ref                                                                                           │
│                                                                                                                                                                 │
│ Schemas and migrations will NOT be touched.                                                                                                                     │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
Continue? [y/N]: y
  OK   sch_shared.tbl_player_info truncated
  OK   sch_shared.tbl_player_photo truncated
  OK   sch_shared.tbl_player_positions truncated
  OK   sch_shared.tbl_players truncated
  OK   sch_shared.tbl_countries truncated
  OK   sch_shared.tbl_confederations truncated
  OK   sch_shared.tbl_gender truncated
  OK   sch_infra.scrape_queue truncated
  OK   sch_infra.player_discovery_batch truncated
  OK   sch_infra.player_queue_ref truncated
  OK   sch_shared.tbl_gender re-seeded

Reset complete. Ready to scrape from scratch.
```
</details>
