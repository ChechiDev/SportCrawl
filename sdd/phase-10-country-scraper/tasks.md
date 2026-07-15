# Tasks: Phase 10 — Country Scraper

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 380–500 |
| 400-line budget risk | Medium–High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 (domain + migration + ORM) → PR 2 (scraper + factory + runtime + linter) |
| Delivery strategy | ask-on-risk |
| Chain strategy | stacked-to-main |

Decision needed before apply: No — all decisions resolved (see below)
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Resolved decisions

- **CountryRepository session**: `session_factory: Callable[[], AsyncSession]` closure injected into `serve()` (same pattern as `JobLoop`). `CountryScraper.__init__` receives a `repo_factory: Callable[[], CountryRepository]` that internally calls `session_factory`. Each `fetch_and_parse` call opens its own session scope — no shared session across jobs.
- **Spike**: Task 1.1 runs first, before any fixture HTML is written.
- **PR validation gates**: PR 1 must be merged AND migration verified on a real DB before PR 2 starts. PR 2 must be merged AND real scraping tested against fbref.com before Phase 11 begins.

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Domain models + ORM + migration | PR 1 | Base: main; includes `domains/country/models.py`, ORM model, migration p10a, `__init__.py` |
| 2 | Scraper + factory + runtime + linter | PR 2 | Base: PR 1 branch or main after merge; `infrastructure/scraping/`, `runtime.py`, `pyproject.toml`, tests |

---

## Phase 1: Spike

- [ ] 1.1 **Fetch `fbref.com/en/countries/` once** using a throwaway async script (or Python REPL + aiohttp). Inspect raw HTML: confirm the countries table CSS `id` attribute, verify `<a href="/en/countries/{CODE}/">` shape, identify which `<td>` indices carry name, confederation, and num_clubs. Record findings as a comment at the top of `infrastructure/scraping/countries.py`. This is a READ-ONLY investigation — no code committed.

---

## PR 1 Gate: merge → run `alembic upgrade head` on real DB → confirm `sch_shared.tbl_countries` exists → only then start PR 2

---

## Phase 2: Domain Foundation (PR 1)

- [ ] 2.1 **Create `domains/country/models.py`** — define `CountryRawData(BaseModel)` with fields `fbref_id` (str, min_length=2, max_length=3), `name` (str, min_length=1), `code` (str, min_length=2, max_length=3), `confederation` (str | None), `num_clubs` (int | None). Define `CountryPage(BaseModel)` with `countries: list[CountryRawData]`. Zero infrastructure imports.
- [ ] 2.2 **RED: write failing unit tests for `CountryRawData`** in `tests/unit/domains/country/test_models.py` — test valid construction, `ValidationError` on missing `name`, `ValidationError` on missing `code`, `ValidationError` on `fbref_id` shorter than 2 chars.
- [ ] 2.3 **GREEN: confirm `CountryRawData` and `CountryPage` pass all model tests** (task 2.2 tests must go green with the implementation from 2.1; no new code needed if Pydantic constraints suffice).
- [ ] 2.4 **Modify `domains/country/__init__.py`** — export `CountryRawData` and `CountryPage`.

---

## Phase 3: Persistence Layer (PR 1 continued)

- [ ] 3.1 **Create `infrastructure/persistence/models/shared/country.py`** — define `tbl_countries` SQLAlchemy ORM model in `sch_shared` schema: `id` UUID PK `server_default gen_random_uuid()`, `fbref_id` VARCHAR(10) UNIQUE NOT NULL, `name` VARCHAR(100) NOT NULL, `code` VARCHAR(3) NOT NULL, `confederation` VARCHAR(50) NULL, `num_clubs` INTEGER NULL, `created_at` TIMESTAMPTZ `server_default now()`, `updated_at` TIMESTAMPTZ NULL. `UniqueConstraint("fbref_id", name="uq_countries_fbref_id")`.
- [ ] 3.2 **Create Alembic migration `infrastructure/persistence/migrations/versions/p10a_create_country.py`** — `revision = "p10a_create_country"`, `down_revision = "p8c_create_sch_football"`. `upgrade()` creates `sch_shared.tbl_countries` with all columns and the unique constraint. `downgrade()` drops the table.
- [ ] 3.3 **Create `infrastructure/persistence/repositories/country.py`** — define `CountryRepository` with `async def upsert(self, rows: list[CountryRawData]) -> None` using PostgreSQL `INSERT ... ON CONFLICT (fbref_id) DO UPDATE SET name=excluded.name, code=excluded.code, confederation=excluded.confederation, num_clubs=excluded.num_clubs, updated_at=now()`. Accept `AsyncSession` at construction.
- [ ] 3.4 **RED: write failing migration test** in `tests/unit/infrastructure/persistence/test_p10a_migration.py` — verify Alembic offline upgrade/downgrade script for `p10a_create_country` is valid (use `alembic upgrade --sql` offline mode to check SQL is generated without error).

---

## Phase 4: Scraper Implementation (PR 2)

- [ ] 4.1 **Create `infrastructure/scraping/__init__.py`** — empty package marker.
- [ ] 4.2 **RED: write failing parse tests** in `tests/unit/infrastructure/scraping/test_countries.py` — use a `MockEngine(ScrapingEngine)` returning fixture HTML (minimal countries table with one row containing `href="/en/countries/ENG/"`, name "England", confederation "UEFA", num_clubs 92). Test: `parse()` extracts `fbref_id="ENG"`, `name="England"`, `confederation="UEFA"`, `num_clubs=92`; lowercase href `/en/countries/eng/` → `fbref_id="ENG"` (`.upper()` normalization); empty table → `CountryPage(countries=[])`; missing table → `ParsingError`; `CountryRawData` missing `name` → `ValidationError`.
- [ ] 4.3 **Create `infrastructure/scraping/countries.py`** — implement `CountryScraper(BaseScraper[CountryPage])`. Class-level `_HREF_RE = re.compile(r"/en/countries/([A-Za-z]{2,3})/", re.IGNORECASE)`. Constructor: `(engine: ScrapingEngine, settings: ScraperConfig, repo: CountryRepository)`. `async def parse(self, html: str) -> CountryPage`: locate the countries table (CSS id confirmed by spike task 1.1); iterate `<tr>` rows; regex `href` → `fbref_id.upper()`; extract name, confederation, num_clubs from named `<td>` cells; build `CountryRawData` per row; no table found → raise `ParsingError`; no rows → return `CountryPage(countries=[])`; after building page call `await self._repo.upsert(page.countries)` and return page.
- [ ] 4.4 **GREEN: run all parse tests** from task 4.2 against implementation in task 4.3. All must pass.

---

## Phase 5: Factory and Runtime Wiring (PR 2 continued)

- [ ] 5.1 **RED: write failing factory tests** in `tests/unit/infrastructure/scraping/test_countries.py` (same file) — test: `scraper_factory("https://fbref.com/en/countries/")` returns `CountryScraper`; `scraper_factory("https://fbref.com/en/unknown/")` raises `ScraperError` (not `ValueError`); two factory calls for country URLs return scrapers sharing the same `browser_engine` instance (assert `is` identity).
- [ ] 5.2 **Modify `infrastructure/work_server/runtime.py`** — (a) add `browser_engine = PydollEngine()` before `JobLoop` construction; (b) define `scraper_factory` closure over `browser_engine`, `scraping`, and a `CountryRepository` factory: if `"fbref.com/en/countries" in url` return `CountryScraper(browser_engine, scraping, CountryRepository(session))`… NOTE: because `CountryRepository` needs a session, the factory closure must either accept a session arg or the scraper receives a repo factory. Resolve: pass a `repo_factory: Callable[[AsyncSession], CountryRepository]` closure; `CountryScraper.__init__` accepts `CountryRepository` directly, so the `scraper_factory` must be adapted — see risk note below; (c) update shutdown sequence to add `await browser_engine.close()` (in `try/except Exception`, log-and-continue) between `wait_for(jobloop_task)` and `engine.dispose()`; (d) remove `_noop_scraper_factory`.
- [ ] 5.3 **GREEN: run factory tests** from task 5.1 against wiring in task 5.2.

---

## Phase 6: Import-Linter Contract (PR 2 continued)

- [ ] 6.1 **Modify `pyproject.toml`** — in `[[tool.importlinter.contracts]]` for "infrastructure adapters do not import each other": (a) add `"infrastructure.scraping"` to the `modules` list; (b) add `"infrastructure.work_server.runtime -> infrastructure.scraping.countries"` to the `ignore_imports` list.
- [ ] 6.2 **Verify `lint-imports` passes** — run `uv run lint-imports` (or equivalent); confirm zero violations. If a violation is reported for `infrastructure.scraping -> domains.country`, that is expected and correct (allowed direction); only domain→scraping violations must be absent.

---

## PR 2 Gate: merge → real scraping test against fbref.com → confirm data in `sch_shared.tbl_countries` → only then Phase 11

---

## Phase 7: Integration Verification

- [ ] 7.1 **Run full test suite** — `uv run pytest` must be green; no pre-existing tests may regress.
- [ ] 7.2 **Verify migration chain** — run `alembic upgrade head --sql` offline; confirm `p10a_create_country` appears after `p8c_create_sch_football` in the SQL output and creates `sch_shared.tbl_countries`.
- [ ] 7.3 **Smoke-test scraper_factory routing** — in a local REPL or dedicated smoke script: confirm `scraper_factory("https://fbref.com/en/countries/")` instantiates a `CountryScraper` without error; confirm `scraper_factory("https://fbref.com/en/unknown/")` raises `ScraperError`.

---

## Risk Notes

1. **`CountryRepository` session binding**: RESOLVED. `serve()` creates a `session_factory` (same as `JobLoop`). `CountryScraper.__init__` receives a `repo_factory: Callable[[], CountryRepository]` closure over that `session_factory`. Each `fetch_and_parse` call opens its own session scope. No shared session across concurrent jobs.

2. **Spike dependency**: tasks 4.2 and 4.3 depend on spike findings (exact table `id`, cell positions). Write fixture HTML only AFTER spike confirms the selector. If fbref changes structure, update fixture immediately.

3. **`CountryRepository` not in design File Changes list**: the design's data flow diagram shows upsert but the File Changes table omits `repositories/country.py`. Task 3.3 adds it explicitly; this is the correct location per hexagonal architecture conventions in this project.
