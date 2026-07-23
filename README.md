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

SportCrawl is driven entirely from the CLI. Every command runs a **preflight check** before scraping — verifying the database connection, schema version, and seed data. Missing data is fixed automatically before the scrape starts.

---

## Run the pipeline

Runs the full pipeline: Teams, Players, and Player Info in parallel with a single command.

```bash
# All countries
uv run sportcrawl --all --workers 5

# One or more specific countries
uv run sportcrawl --country ESP --workers 3
uv run sportcrawl --country ESP,ARG,BRA --workers 5
```

The three scraping stages run concurrently in a single unified display:

- **Scraping Teams** — starts immediately, scrapes club listings per country
- **Scraping Players** — starts immediately in parallel with Teams
- **Scraping Single Player Stats** — starts automatically once enough players are in the database

| Flag | Description |
|---|---|
| `--country` | Comma-separated FBRef country codes (e.g. `ESP,ARG`) |
| `--all` | Run pipeline for all countries available in the database |
| `--workers N` | Number of parallel workers per stage (default: `1`) |
| `--with-player-info` | Include individual player profile scraping |
| `--skip-preflight` | Skip the preflight check |
| `--recover-stale` | Reset jobs stuck in `IN_PROGRESS` for over 1 hour |

> For best results and to avoid rate limiting, **3–5 workers is recommended**.

> **Heads up:** scraping all players and their individual profiles across all countries means hundreds of thousands of requests. This can take several hours depending on the number of workers and your network conditions.

## Scraping Example

```bash
❯ uv run sportcrawl --all --workers 5
───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
   _____ ____  ____  ____  ______   __________  ___ _       ____ 
  / ___// __ \/ __ \/ __ \/_  __/  / ____/ __ \/   | |     / / / 
  \__ \/ /_/ / / / / /_/ / / /    / /   / /_/ / /| | | /| / / /  
 ___/ / ____/ /_/ / _, _/ / /    / /___/ _, _/ ___ | |/ |/ / /___
/____/_/    \____/_/ |_| /_/     \____/_/ |_/_/  |_|__/|__/_____/
                                                                 
  Sports data, scraped at scale.  v0.18.0
  Ctrl+C to stop  ·  on restart, scraping resumes from where it left off
───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

Checking requirements...
  ✓  Connected successfully.                                
  ✓  Migrations initialized successfully.                   
  ✓  Database version up to date.                           
  ✓  Database schemas verified.                             
  ✓  System tables ready.                                   
  ✓  219 countries loaded.                                        
  ✓  96 country squads loaded.                                        

───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

Scraping Teams
  RUN  [Crawl-1] [14 | 67/96] Nicaragua: 1 teams                                                                                                                   
  RUN  [Crawl-2] [14 | 67/96] Netherlands: 62 teams                                                                                                                
  RUN  [Crawl-3] [13 | 67/96] Malta: 15 teams                                                                                                                      
  RUN  [Crawl-4] [13 | 67/96] Montenegro: 18 teams                                                                                                                 
  RUN  [Crawl-5] [13 | 67/96] Martinique: 4 teams                                                                                                                  

Scraping Players
  RUN  [Crawl-1] [12 | 60/219] Djibouti: 118 players                                                                                                               
  RUN  [Crawl-2] [12 | 60/219] Côte D'Ivoire: 879 players                                                                                                          
  RUN  [Crawl-3] [12 | 60/219] Czechoslovakia: 173 players                                                                                                         
  RUN  [Crawl-4] [12 | 60/219] Czech Republic: 1,648 players                                                                                                       
  RUN  [Crawl-5] [12 | 60/219] Denmark: 2,360 players                                                                                                              

Scraping Single Player Stats
  RUN  [Crawl-1] [18 | 87/48520] Player Name
  RUN  [Crawl-2] [18 | 87/48520] Player Name
  RUN  [Crawl-3] [17 | 87/48520] Player Name
  RUN  [Crawl-4] [17 | 87/48520] Player Name
  RUN  [Crawl-5] [17 | 87/48520] Player Name
```

---

## Reset Database

Truncates all scraped data from the database. Useful for testing or starting fresh.

```bash
uv run sportcrawl reset
```

> This only clears scraped data. It does not drop schemas or roll back migrations.

## Reset Example
```bash
❯ uv run sportcrawl reset
╭────────────────────────────── Reset Database ──────────────────────────────╮
│ WARNING                                                                     │
│                                                                             │
│ This will delete ALL scraped data:                                          │
│   • sch_shared: countries, players, player_info, photos, positions,         │
│     country_squads, teams, competition                                      │
│   • sch_infra: scrape_queue, player_discovery_batch, player_queue_ref       │
│                                                                             │
│ Schemas and migrations will NOT be touched.                                 │
╰─────────────────────────────────────────────────────────────────────────────╯
Continue? [y/N]: y
  OK   sch_shared.tbl_player_info truncated
  OK   sch_shared.tbl_player_photo truncated
  OK   sch_shared.tbl_player_positions truncated
  OK   sch_shared.tbl_players truncated
  OK   sch_shared.tbl_teams truncated
  OK   sch_shared.tbl_country_squads truncated
  OK   sch_shared.tbl_competition truncated
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
