# Phase 10 — Scraping Engine (Countries): Specification

## Purpose

This spec describes the behavioral contracts introduced by Phase 10: the first working end-to-end scrape of Countries data from fbref. It covers the domain model, scraper, persistence, factory routing, engine lifecycle, and import-linter contract.

---

## Domains Covered

| Domain | Type |
|--------|------|
| `country-scraping` | New (full spec) |

---

## Requirements

---

### Requirement: CountryRawData Domain Model

The `CountryRawData` type MUST represent a single parsed country record as a pure value object. It MUST contain at minimum: `fbref_id` (a 2–3 character code extracted from the fbref href), `name` (the country name), and `code` (the 2–3 char ISO-style country code). It MUST NOT import any infrastructure or persistence modules. All fields MUST be validated at construction time.

#### Scenario: Valid country record construction

- GIVEN a `fbref_id`, `name`, and `code` are available
- WHEN a `CountryRawData` is constructed with those values
- THEN the object is valid and each field is accessible

#### Scenario: Construction fails on missing required field

- GIVEN `fbref_id`, `name`, or `code` is absent
- WHEN a `CountryRawData` is constructed
- THEN a validation error is raised before the object is returned

---

### Requirement: CountryScraper Parsing Contract

`CountryScraper` MUST fetch the fbref countries page and return a list of `CountryRawData` records — one per country row. It MUST extract the country code from the fbref URL pattern (`/en/countries/{CODE}/`). It MUST NOT persist data itself. If the page yields no rows, it MUST return an empty list (not raise). If the page structure is unrecognised, it MUST raise a scraper-domain exception (not a raw HTML or network error).

#### Scenario: Successful parse returns country list

- GIVEN the fbref countries page is reachable and contains country rows
- WHEN `CountryScraper` fetches and parses the page
- THEN a non-empty list of `CountryRawData` is returned
- AND each record has a non-empty `fbref_id`, `name`, and `code`

#### Scenario: Page with no country rows returns empty list

- GIVEN the fbref countries page is reachable but contains no country rows
- WHEN `CountryScraper` fetches and parses the page
- THEN an empty list is returned without raising

#### Scenario: Unrecognised page structure raises scraper exception

- GIVEN the fetched page does not match the expected country table structure
- WHEN `CountryScraper` attempts to parse it
- THEN a scraper-domain exception is raised
- AND no raw HTML parsing error propagates to the caller

#### Scenario: Country code extracted from URL

- GIVEN a country row whose href is `/en/countries/ENG/`
- WHEN `CountryScraper` parses that row
- THEN the resulting `CountryRawData.fbref_id` equals `"ENG"`

---

### Requirement: tbl_countries ORM and Migration

`tbl_countries` MUST reside in the `sch_shared` schema. It MUST have at minimum: a surrogate primary key, a unique `fbref_id`, a `name`, and a `code`. The Alembic migration `p10a_create_country` MUST create the table on upgrade and drop it on downgrade. The table MUST NOT reference any `sch_football`-scoped table.

#### Scenario: Migration upgrade creates table

- GIVEN the database is at the pre-p10a revision
- WHEN the `p10a_create_country` upgrade is applied
- THEN `sch_shared.tbl_countries` exists with the required columns

#### Scenario: Migration downgrade removes table

- GIVEN the database is at the p10a revision
- WHEN the `p10a_create_country` downgrade is applied
- THEN `sch_shared.tbl_countries` no longer exists

#### Scenario: Country code is unique

- GIVEN `tbl_countries` already contains a row with `fbref_id` `"ENG"`
- WHEN a second row with `fbref_id` `"ENG"` is inserted
- THEN the database rejects the insertion with a unique constraint violation

---

### Requirement: Scraper Factory URL Routing

The scraper factory in `runtime.py` MUST return a `CountryScraper` when the job URL matches the fbref countries pattern. It MUST raise a `ScraperError` (not a plain `ValueError` or sentinel) for URLs that do not match any known pattern, so that `JobLoop._process` can record the failure and mark the queue row terminal. It MUST use the single shared `PydollEngine` instance — it MUST NOT create a new engine per factory call.

#### Scenario: Country URL routes to CountryScraper

- GIVEN a job with URL `https://fbref.com/en/countries/`
- WHEN the scraper factory is called with that URL
- THEN a `CountryScraper` instance backed by the shared engine is returned

#### Scenario: Unknown URL raises ScraperError

- GIVEN a job with URL that does not match any known pattern
- WHEN the scraper factory is called with that URL
- THEN a `ScraperError` is raised — NOT a `ValueError`, NOT a noop scraper

#### Scenario: Factory does not create a new engine per call

- GIVEN the scraper factory has been called once for a country URL
- WHEN the factory is called again for a second country URL
- THEN both returned scrapers share the same underlying engine instance

---

### Requirement: PydollEngine Shared Lifecycle in serve()

`serve()` MUST create exactly ONE `PydollEngine` instance for the lifetime of the server process. The engine MUST be passed (via closure or explicit injection) to the scraper factory so all scrapers share it. On shutdown, the engine lifecycle MUST follow this order: (1) drain the `JobLoop`, (2) call `browser_engine.close()`, (3) call `engine.dispose()`. The engine MUST NOT be closed before the `JobLoop` is fully drained.

#### Scenario: Single engine created on serve()

- GIVEN `serve()` is called
- WHEN the server initialises
- THEN exactly one `PydollEngine` is instantiated

#### Scenario: Correct shutdown order

- GIVEN the server is running and receives a shutdown signal
- WHEN shutdown proceeds
- THEN the `JobLoop` drains before `browser_engine.close()` is called
- AND `browser_engine.close()` completes before `engine.dispose()` is called

#### Scenario: Engine not closed mid-flight

- GIVEN a scrape job is in progress
- WHEN a shutdown signal arrives concurrently
- THEN `browser_engine.close()` is not called before the JobLoop task completes (cancelled or not) — best-effort under cancellation, not a hard real-time guarantee

#### Scenario: browser_engine.close() raises during shutdown

- GIVEN `serve()` is in the shutdown sequence
- AND `browser_engine.close()` raises an exception
- THEN the exception is caught and logged
- AND `engine.dispose()` is still called
- AND the process exits cleanly

---

### Requirement: Import-Linter Independence Contract for infrastructure.scraping

Domain layers MUST NOT import from `infrastructure.scraping`. The `infrastructure.scraping` package MAY import from `domains/` (e.g. `CountryRawData`). The independence contract in `pyproject.toml` MUST prevent `domains` from importing `infrastructure.scraping`, NOT the reverse. The import-linter check MUST pass after the contract is updated.

#### Scenario: Independence contract updated

- GIVEN `pyproject.toml` does not yet list `infrastructure.scraping` in the independence contract
- WHEN the contract is updated and `lint-imports` is run
- THEN no violations are reported

#### Scenario: Violation caught if domain imports scraping internals

- GIVEN a module under `domains/` imports a symbol from `infrastructure.scraping`
- WHEN `lint-imports` is run
- THEN a contract violation is reported

---

## Non-Goals (spec-level exclusions)

The following MUST NOT appear in Phase 10 deliverables:

- Flag images, governing body references, gender fields, or player/team data
- Cloudflare `cf_clearance` bypass logic
- URL registry abstraction (a plain if/elif factory is sufficient until 3+ domains)
- Any table in `sch_football` referencing countries
