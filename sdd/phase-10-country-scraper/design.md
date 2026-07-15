# Design: Phase 10 — Scraping Engine (Countries)

## Technical Approach

Implements Approach 1 from the proposal: a new `infrastructure/scraping/` package holding a concrete `CountryScraper`, a pure-domain `CountryRawData` model in `domains/country/`, a `tbl_countries` ORM + migration in `sch_shared`, and a real URL-routing `scraper_factory` in `runtime.py` backed by a single shared `PydollEngine`. Base scraping infra (`ScrapingEngine`, `BaseScraper`, `PydollEngine`, `JobLoop`) is reused unchanged.

## Architecture Decisions

### Decision: CountryScraper base class → `BaseScraper`, NOT `BaseMultiTableScraper`

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `BaseMultiTableScraper` | `parse_tables` receives `dict[str, pd.DataFrame]` built via `pd.read_html`, which **discards `<a href>` attributes** | Rejected |
| `BaseScraper` + BeautifulSoup | Full control over the DOM; href survives for `fbref_id` regex | **Chosen** |

**Rationale**: `fbref_id` MUST come from the row's `href` (`/en/country/{CODE}/Country-Name`). `pd.read_html` flattens cells to text, so the href is gone before `parse_tables` runs. The spike still runs to confirm the countries table structure, but the DataFrame-vs-DOM constraint already forecloses `BaseMultiTableScraper`. No code change to `ports/scraper.py`.

### Decision: `parse()` returns a list wrapper, not a scalar

`BaseScraper.parse(html) -> T_co` returns ONE model; Countries yields many rows. `CountryRawData` stays the per-row value object; `CountryScraper.parse` returns a `CountryPage(BaseModel)` container with `countries: list[CountryRawData]`. `T_co = CountryPage`. Empty page → `CountryPage(countries=[])` (no raise, per spec). Unrecognised structure → `ParsingError`.

### Decision: Upsert on `fbref_id`

Persistence uses PostgreSQL `INSERT ... ON CONFLICT (fbref_id) DO UPDATE` so re-scrapes are idempotent. `fbref_id` carries the `UNIQUE` constraint that is also the conflict target.

### Decision: Two distinct engines in `serve()`

`serve()` already owns a SQLAlchemy `engine` (`.dispose()`). Phase 10 adds a SEPARATE `PydollEngine` (`.close()`). Named `browser_engine` to avoid shadowing.

## Data Flow

    JobLoop ─→ scraper_factory(url) ─→ CountryScraper(browser_engine)
                                          │ fetch_and_parse(url)
                                          ▼
              PydollEngine.fetch ─→ html ─→ parse() ─→ CountryPage
                                          │
              CountryRepository.upsert(rows) ─→ sch_shared.tbl_countries

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `domains/country/models.py` | Create | `CountryRawData`, `CountryPage` Pydantic models |
| `domains/country/__init__.py` | Modify | Export the models |
| `infrastructure/scraping/__init__.py` | Create | Package marker |
| `infrastructure/scraping/countries.py` | Create | `CountryScraper(BaseScraper[CountryPage])` |
| `infrastructure/persistence/models/shared/country.py` | Create | `tbl_countries` ORM (`sch_shared`) |
| `.../migrations/versions/p10a_create_country.py` | Create | Create/drop table |
| `infrastructure/work_server/runtime.py` | Modify | Real factory + `PydollEngine` lifecycle |
| `pyproject.toml` | Modify | Add `infrastructure.scraping` to the independence contract `modules` list AND add an `ignore_imports` exemption `"infrastructure.work_server.runtime -> infrastructure.scraping.countries"` (same pattern as existing `ignore_imports` entries) — required because `runtime.py` imports `CountryScraper` from `infrastructure.scraping.countries` |
| `tests/unit/infrastructure/scraping/test_countries.py` | Create | Parse + factory tests |

## Interfaces / Contracts

```python
# domains/country/models.py — NO infrastructure imports
class CountryRawData(BaseModel):
    fbref_id: str      # from href /en/country/([A-Za-z]{2,3})/ — FBRef code (AFG, ALB); min_length=2, max_length=3
    name: str          # td[data-stat='country'] text; min_length=1
    code: str          # td[data-stat='flag'] text → .upper() — ISO 3166-1 alpha-2 (AF, AL); min_length=2, max_length=2
    confederation: str | None = None
    num_clubs: int | None = None

class CountryPage(BaseModel):
    countries: list[CountryRawData]

# infrastructure/scraping/countries.py
class CountryScraper(BaseScraper[CountryPage]):
    _HREF_RE = re.compile(r"/en/country/([A-Za-z]{2,3})/", re.IGNORECASE)
    # fbref_id normalised to .upper() after match; IGNORECASE guards any case variation.
    async def parse(self, html: str) -> CountryPage:
        # BeautifulSoup(html, "lxml"); locate table id="countries" (10 tables on page, last one);
        # iterate tbody rows; regex href on td[data-stat='country'] → fbref_id;
        # td[data-stat='flag'].get_text().upper() → code;
        # td[data-stat='governing_body'].get_text() → confederation;
        # int(td[data-stat='club_count'].get_text() or 0) → num_clubs;
        # no table found → raise ParsingError; no rows → CountryPage(countries=[])
```

**`tbl_countries`** (`sch_shared`): `id` UUID PK `server_default gen_random_uuid()`; `fbref_id` VARCHAR(10) UNIQUE NOT NULL; `name` VARCHAR(100) NOT NULL; `code` VARCHAR(3) NOT NULL; `confederation` VARCHAR(50) NULL; `num_clubs` INTEGER NULL; `created_at` TIMESTAMPTZ `server_default now()`; `updated_at` TIMESTAMPTZ. `__table_args__ = (UniqueConstraint("fbref_id", name="uq_countries_fbref_id"), {"schema": "sch_shared"})`.

**`scraper_factory`** (closure over `browser_engine`, `scraping`):
```python
def scraper_factory(url: str) -> BaseScraper[Any]:
    if "fbref.com/en/countries" in url:
        return CountryScraper(browser_engine, scraping)
    raise ScraperError(f"No scraper registered for URL: {url}")
```
Defined inside `serve()` so both scrapers share `browser_engine`.

**Engine lifecycle**: create `browser_engine = PydollEngine()` just before `JobLoop` construction; inject `scraper_factory`. Shutdown order becomes: site.stop → runner.cleanup → JobLoop drain → `await browser_engine.close()` (wrapped in try/except, log-and-continue if it raises — MUST NOT block `dispose`) → `engine.dispose()`.

**Note**: the current `runtime.py` drain uses `jobloop_task.cancel()`. This sends `CancelledError` into any in-flight `fetch_and_parse()`. The "not closed mid-flight" guarantee is best-effort under cancellation — a full cooperative-stop mechanism is out of scope for Phase 10. The `browser_engine.close()` is called after `wait_for(jobloop_task)` completes (cancelled or not), which is sufficient for Phase 10.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `parse()` extracts fbref_id/name/code from fixture HTML; href regex yields `"ENG"`; lowercase href (e.g. `/en/country/eng/`) → row included with `fbref_id="ENG"` (normalised via `.upper()`); empty table → `[]`; malformed → `ParsingError` | In-file `MockEngine(ScrapingEngine)` returning fixture HTML; `ScrapingSettings` with zeroed delays |
| Unit | `CountryRawData` rejects missing `name`/`code` | Direct Pydantic construction asserting `ValidationError` |
| Unit | factory(country_url) → `CountryScraper`; factory(unknown) → `ScraperError`; two calls share one engine | Call the closure directly; assert `is` identity of engine |
| Migration | (deferred to apply) upgrade/downgrade create/drop `sch_shared.tbl_countries` | Alembic offline check |

## Spike / Rollout

**Spike (first apply task)**: fetch `fbref.com/en/countries/` once, inspect the countries table — confirm the row `<a href>` shape and which cells carry name/confederation/clubs. This validates the CSS/row selectors and confirms the DataFrame constraint above; base class stays `BaseScraper` regardless.

**Migration**: `p10a_create_country`, `down_revision = "p8c_create_sch_football"`. `upgrade` creates the table (UUID PK via `gen_random_uuid()`, unique `fbref_id`); `downgrade` drops it. Additive; rollback restores `_noop_scraper_factory` and drops the table.

## Open Questions

- [x] Exact fbref countries table `id`/CSS selector and confederation/num_clubs cell positions — **resolved by spike**:
  - Table: `id="countries"` (last of 10 tables on page)
  - href shape: `/en/country/{CODE}/Country-Name` (singular — design originally had wrong plural)
  - Columns: `data-stat='country'` [0]=name+href, `flag` [1]=ISO-2 code, `governing_body` [2]=confederation, `club_count` [3]=num_clubs
  - `code` = ISO 3166-1 alpha-2 (always 2 chars, max_length=2), NOT same as fbref_id
  - 225 country rows total
  - Non-headless Chromium required to bypass Cloudflare (DISPLAY=:0 works in WSL)
