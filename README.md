<div align="center">

<img src="https://raw.githubusercontent.com/ChechiDev/SportCrawl/main/assets/images/sportcrawl-logo-wip.png" alt="SportCrawl Logo" width="1024" />

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
- Competitions (leagues, cups, international tournaments) — auto-seeded from FBRef at startup
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

SportCrawl is driven entirely from the CLI. Every command runs a **preflight check** before scraping — verifying the database connection, schema version, and seed data. Missing data is fixed automatically before the scrape starts.

---

## Run the pipeline

Runs the full pipeline: Teams, Players, and Player Info in parallel with a single command.

```bash
# All countries
uv run sportcrawl start -a -w 5

# One or more specific countries
uv run sportcrawl start -c ESP -w 3
uv run sportcrawl start -c ESP,ARG,BRA -w 5
```

The three scraping stages run concurrently in a single unified display:

- **Scraping Teams** — starts immediately, scrapes club listings per country
- **Scraping Players** — starts immediately in parallel with Teams
- **Scraping Single Player Stats** — starts automatically once enough players are in the database

| Flag | Shorthand | Description |
|---|---|---|
| `--all` | `-a` | Run pipeline for all countries in the database |
| `--country` | `-c` | Comma-separated FBRef country codes (e.g. `ESP,ARG`) |
| `--workers N` | `-w N` | Number of parallel workers per stage (default: `1`) |
| `--with-player-info` | — | Include individual player profile scraping |
| `--skip-preflight` | — | Skip the preflight check |
| `--recover-stale` | — | Reset jobs stuck in `IN_PROGRESS` for over 1 hour |

> For best results and to avoid rate limiting, **3–5 workers is recommended**.

> **Heads up:** scraping all players and their individual profiles across all countries means hundreds of thousands of requests. This can take several hours depending on the number of workers and your network conditions.

## Scraping Example

```console
❯ uv run sportcrawl -a -w 5 
────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
   _____ ____  ____  ____  ______   __________  ___ _       ____ 
  / ___// __ \/ __ \/ __ \/_  __/  / ____/ __ \/   | |     / / / 
  \__ \/ /_/ / / / / /_/ / / /    / /   / /_/ / /| | | /| / / /  
 ___/ / ____/ /_/ / _, _/ / /    / /___/ _, _/ ___ | |/ |/ / /___
/____/_/    \____/_/ |_| /_/     \____/_/ |_/_/  |_|__/|__/_____/
                                                                 
  Sports data, scraped at scale.  v0.24.1
  Ctrl+C to stop  ·  on restart, scraping resumes from where it left off
────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

Checking requirements...
  ✓  Connected successfully.                                
  ✓  Migrations initialized successfully.                   
  ✓  Database schemas verified.                             
  ✓  System tables ready.                                   
  ✓  225 Countries loaded successfully.      
  ✓  96 Country Teams loaded successfully.        
  ✓  224 Countries with Players loaded successfully.    
  ✓  152 Competitions loaded successfully.      

────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

Scraping All Teams by Country
  ✓  All teams in 96 countries scraped                                                                                              

Scraping All Players by Country
  ✓  All players in 224 countries already scraped                                                                                   

Scraping Player Profile & Stats
  RUN  [Crawl-1] [102 | 535/229300] Dean Lico                                                                                       
  RUN  [Crawl-2] [106 | 535/229300] Ermir Lenjani                                                                                   
  RUN  [Crawl-3] [112 | 535/229300] Suad Liçi                                                                                       
  RUN  [Crawl-4] [110 | 535/229300] Venssa Levendi                                                                                  
  RUN  [Crawl-5] [105 | 535/229300] Vanesa Levenaj
```

---

## Reset Database

Drops all schemas, replays every migration from scratch, then truncates all scraped data. Useful for testing or starting completely fresh.

```bash
uv run sportcrawl reset
```

> **Note:** `reset` drops and recreates all schemas from scratch. Migrations are re-applied automatically — no manual `alembic upgrade head` needed.

## Reset Example
```console
❯ uv run sportcrawl reset -y
╭───────────────────────────── Reset Database ─────────────────────────────╮
│ WARNING                                                                    │
│                                                                            │
│ This will delete ALL scraped data:                                         │
│   • sch_fbref_shared: countries, players, player_info, photos, positions,  │
│     country_squads, teams, competition, comp_type, cities, player_citizenship│
│   • sch_fbref_football: player_std_stats, player_misc_stats,               │
│     player_playing_time_stats, player_shooting_stats                       │
│   • sch_fbref_infra: scrape_queue, player_discovery_batch, player_queue_ref│
│                                                                            │
│ Schemas and migrations will NOT be touched.                                │
╰────────────────────────────────────────────────────────────────────────────╯
  OK   sch_fbref_football.tbl_player_misc_stats truncated
  OK   sch_fbref_football.tbl_player_playing_time_stats truncated
  OK   sch_fbref_football.tbl_player_shooting_stats truncated
  OK   sch_fbref_football.tbl_player_std_stats truncated
  OK   sch_fbref_shared.tbl_player_info truncated
  OK   sch_fbref_shared.tbl_player_photo truncated
  OK   sch_fbref_shared.tbl_player_citizenship truncated
  OK   sch_fbref_shared.tbl_player_positions truncated
  OK   sch_fbref_shared.tbl_players truncated
  OK   sch_fbref_shared.tbl_teams truncated
  OK   sch_fbref_shared.tbl_country_squads truncated
  OK   sch_fbref_shared.tbl_competition truncated
  OK   sch_fbref_shared.tbl_comp_type truncated
  OK   sch_fbref_shared.tbl_cities truncated
  OK   sch_fbref_shared.tbl_countries truncated
  OK   sch_fbref_shared.tbl_confederations truncated
  OK   sch_fbref_shared.tbl_gender truncated
  OK   sch_fbref_infra.scrape_queue truncated
  OK   sch_fbref_infra.player_discovery_batch truncated
  OK   sch_fbref_infra.player_queue_ref truncated
  OK   sch_fbref_shared.tbl_gender re-seeded

Reset complete. Ready to scrape from scratch.
```
