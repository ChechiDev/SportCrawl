# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.37.0] — 2026-08-27

### Fixed

- **Gate 7 startup diagnostic evidence**: when `work_server.startup()` raises, the BLOCKED report now includes `startup_error_type` (exception class name) and `startup_error` (truncated, redacted exception message) — previously the exception was swallowed with no diagnostic context
- **Gate 14 ValueError diagnostic evidence**: when `clearance_post.post()` raises `ValueError`, the FAIL report now includes `post_error_type`, `post_error` (truncated, redacted), and `clearance_class` (label only, never raw cookie) — previously the ValueError path returned no diagnostic evidence
- **Gate 12 error evidence companion key**: `clearance_getter_error_type` added alongside the existing `clearance_getter_error` label for both exception paths (`PermissionError` → `"PermissionError"`, `ConnectionError` → `"ConnectionError"`) — establishes consistent pair convention across all error-emitting gates
- **Early-exit redaction bypass**: Gate 7 and Gate 14 early-return paths now apply the same `scan_for_sensitive` redaction + 200-char truncation via `_redact_str()` before placing exception strings in evidence — previously these paths bypassed the final gate scan

### Added

- **`_redact_str()` helper**: private method on `RealClearanceHarness` applying `scan_for_sensitive` redaction and 200-char truncation to exception strings before they land in evidence
- **Harness-level token-source BLOCKED path tests**: contract tests asserting `GATE_TOKEN_SOURCE` returns BLOCKED for sentinel labels and that later gates are not executed
- **Gate 7/12/14 evidence assertions**: value assertions, `str[:200]` truncation boundary tests, and evidence spread-preservation assertions for all three gate error paths
- **Consistent gate error evidence convention**: all error-emitting gates (7, 12, 14) now use `<component>_error_type` + `<component>_error` key pair — canonical pattern for harness diagnostics
- **4R review suite**: 3 rounds of `review-risk`, `review-resilience`, `review-reliability`, `review-readability` — all four lenses APPROVED before commit

### Notes

- Architecture guardrail: the buffering/session/clearance system remains a **generic multi-web engine**; FBref is only the first adapter/config/policy validation path; no FBref literal appears in core CLI/harness code; Transfermarkt, Capology, and other future adapters remain fully supported
- Real smoke NOT executed; CP-SMOKE-B execution NOT authorized
- B1: real browser/CDP wiring (`cli/main.py:468-469`) remains unresolved and not implemented
- No real work_server, ports, DB, Docker, browser, Chrome, Xvfb, CDP, cookies, network, or live target used in tests
- CP2/session-clearance-pool out of scope and untouched

## [0.36.0] — 2026-08-27

### Fixed

- **Gate 14 ValueError containment**: `ValueError` raised by `RealClearancePostClient.post()` for unknown clearance-class labels is now caught at gate 14 and returned as a FAIL report — previously it escaped the harness uncontained
- **Scoped CI workflow checking**: `GhCICheckProvider` now accepts an optional `workflow_name` filter; wired with `workflow_name="CI"` in `cli/main.py` to prevent non-CI workflow runs (e.g. Release, Deploy) from producing a false `ALL_PASS` result
- **In-progress CI blocking**: the CI gate now returns `BLOCKED` for any run in `in_progress` or `queued` status, even when an older successful run exists in the list
- **Clearance getter auth/transport diagnostics**: `_make_clearance_getter` in `cli/main.py` now raises `PermissionError` on HTTP 401/403, raises `ConnectionError` on transport failure (`URLError`/`OSError`), and propagates unexpected exceptions — previously all errors were silently swallowed with `return None`; gate 12 catches `ConnectionError` and returns a `BLOCKED` report with `clearance_getter_error: "connection_failure"` evidence
- **Malformed clearance GET body handling**: `_make_clearance_getter` wraps JSON parsing in `try/except (KeyError, ValueError, AttributeError)` and returns `None` for malformed 200 responses — previously an unhandled parse error could escape the getter
- **Work-server shutdown waiting after kill**: `RealWorkServerLifecycle.shutdown()` now calls `self._process.wait(timeout=3)` after `kill()` to avoid leaving zombie processes on timeout
- **Token-safe `__repr__`**: `RealWorkServerLifecycle` and `RealClearancePostClient` now implement `__repr__` that renders `token=<redacted>`, preventing accidental token exposure in logs and tracebacks
- **Browser cleanup protocol**: `BrowserLauncher` Protocol gains a `stop() -> None` method; the harness `finally` block now calls `browser_launcher.stop()` before `work_server.shutdown()`, both wrapped in independent `try/except` guards — previously the browser had no cleanup seam
- **`RealBrowserLauncher` teardown seam**: `engine_stopper: Callable[[], Coroutine[Any, Any, None]] | None = None` injectable added to `RealBrowserLauncher`; `stop()` invokes it via `_loop_runner` when present, suppresses all exceptions, and resets `_started = False` unconditionally

### Added

- **Extension convention for clearance-class/domain mapping**: multi-line comment added to `_CLEARANCE_CLASS_TO_DOMAIN` in `cli/clearance_post_client.py` documenting key format (`<cookie_name>@<domain>`) and how to add a new scraping target (Transfermarkt, Capology, etc.)
- **`TestStop` (5 tests)**: unit tests for all `RealBrowserLauncher.stop()` branches — stopper invoked, stopper exception suppressed, `_started` reset regardless of outcome, no-op when stopper absent, safe when never started
- **`TestCleanupAlwaysRuns` full coverage**: all 11 cleanup tests now assert `launcher.stop_called` alongside `ws.shutdown_called` across every gate-failure path including pre-gate-10 BLOCKED paths
- **Context-manager transport tests**: two new tests for `URLError`/`OSError` raised from `__enter__` of the URL open context manager, exercising the distinct branch from exceptions raised at the `getter(req)` call boundary
- **4R review suite**: 3 rounds of `review-risk`, `review-resilience`, `review-reliability`, `review-readability` — all four lenses APPROVED before commit

### Notes

- Architecture guardrail: the buffering/session/clearance system remains a **generic multi-web engine**; FBref is only the first adapter/config/policy validation path; no FBref literal appears in core CLI/harness code; Transfermarkt, Capology, and other future adapters remain fully supported
- Real smoke NOT executed; CP-SMOKE-B execution NOT authorized
- Real browser/CDP start still not implemented or authorized (B1 deferred)
- No real work_server, ports, DB, Docker, browser, Chrome, Xvfb, CDP, cookies, network, or live target used in tests
- CP2/session-clearance-pool out of scope and untouched

## [0.35.0] — 2026-08-26

### Added
- `smoke-clearance --real-clearance` in `cli/main.py` now wires all concrete generic real-clearance seams into `RealClearanceHarness.run()`:
  - Constructs `RealClearanceProviders` with `RealClearanceBrowserLauncher`, `RealClearanceObserver`, `RealClearancePostClient`, and the work-server URL resolver
  - Constructs `RealClearanceSeams` from those providers
  - Invokes `RealClearanceHarness.run(seams)` and maps the result to exit codes: `0` on PASS, `1` on BLOCKED or FAIL
  - Resolved host is loopback-only; work-server command is generic (no site-specific literals in `cli/main.py`)
- 491-line synthetic wire-up test suite in `tests/unit/cli/test_main_real_clearance_wireup.py` covering provider construction, seam wiring, harness invocation, exit-code mapping, loopback-only host resolution, and generic work-server command — no real server, ports, DB, Docker, browser, Chrome, Xvfb, CDP, cookies, network, or live target used

### Notes
- Architecture guardrail: the buffering/session/clearance system is a generic multi-web engine; FBref is only the first adapter/config/policy validation path; no FBref literal appears in `cli/main.py`; Transfermarkt, Capology, and other future adapters remain fully supported by the design
- Real smoke NOT executed; CP-SMOKE-B execution NOT authorized
- No real work_server, ports, DB, Docker, browser, Chrome, Xvfb, CDP, cookies, network, or live target used in tests
- CP2/session-clearance-pool out of scope and untouched

## [0.34.0] — 2026-08-26

### Added
- `RealClearancePostClient` in `cli/clearance_post_client.py`: concrete `ClearancePostClient` seam for real clearance harness gate 14 (post-clearance probe to work server)
- All external interactions are injectable: `poster` (callable `(url, headers, body) -> (status_code, body_bytes)`; default uses `urllib.request` from stdlib — no third-party HTTP dependency), `clock` (default: `datetime.now(UTC)`) — no real server, network, browser, or cookie values in tests
- `post(clearance_class) -> tuple[int, int]`: maps label to domain via `_CLEARANCE_CLASS_TO_DOMAIN`; builds synthetic probe payload with fixed `__smoke_probe_clearance__` placeholder (raw cookie never sent); raises `ValueError` for unknown labels; returns `(status_code, body_bytes)` from poster unchanged
- `clearance_class` is always a label string (e.g. `"cf_clearance@fbref.com"`), never a raw cookie value; `scan_for_sensitive()` guard asserted directly in tests
- 25 synthetic unit tests in `tests/unit/cli/test_clearance_post_client.py` covering URL forwarding, `Authorization: Bearer` header, token isolation from body, exact six-key payload shape, domain mapping, placeholder clearance field, synthetic profile/worker IDs, all-string payload values, timestamp ordering (`observed_at < expires_at`), 60-second expires offset, injected clock determinism, ISO 8601 UTC format, status/body-bytes passthrough (204/0, 500, 401, non-zero bytes), secret safety via `scan_for_sensitive`, and `ValueError` on unknown/empty labels
- 3 harness integration tests confirming gate 14 (`post_clearance`) blocks on non-204 status, blocks on non-zero body bytes, and passes on `(204, 0)`

### Notes
- Real smoke NOT executed; `--real-clearance` remains blocked pending CLI wire-up
- CP-SMOKE-B execution NOT authorized
- `RealClearancePostClient` is NOT wired into `cli/main.py` yet — wiring deferred to a separate authorized MASTER TASK
- No real server, network, browser, Chrome, Xvfb, CDP, cookies, subprocess, DB, Docker, or live target used in tests; `urllib.request` default poster never called in tests (injectable mock only)
- CP2/session-clearance-pool out of scope and untouched

## [0.33.0] — 2026-08-26

### Added
- In-memory sanitized clearance store in `infrastructure/work_server/server.py`: `POST /api/clearance` (existing) now persists sanitized metadata (`domain`, `expires_at`, `observed_at`) to an in-memory dict via `store.update()` after all validation passes — raw `clearance` cookie value is **never** stored, returned, or logged
- `GET /api/clearance/latest` handler: returns 204 when no validated clearance has been received; returns 200 + JSON with sanitized metadata (`domain`, `expires_at`, `observed_at`) after at least one valid POST has been processed; protected by existing `bearer_auth_middleware` (not in auth-exempt set)
- Typed `web.AppKey("clearance_store", dict)` initialized as `{}` in `create_app`; mutated in-place via `store.update()` to avoid aiohttp app-state deprecation warning on post-startup key reassignment
- 16 synthetic unit tests in `tests/unit/infrastructure/test_clearance_store_bridge.py` covering: GET auth (401 without/wrong token, 200/204 with valid token), GET 204 on empty store with empty body, GET 200+JSON after valid POST, GET response excludes `clearance`/`profile_id`/`worker_id` fields, invalid POST (missing field, invalid domain) leaves store unchanged, invalid POST after valid POST does not overwrite, second valid POST overwrites `domain` and `expires_at`

### Notes
- Real smoke NOT executed; `--real-clearance` remains blocked pending remaining seam implementations
- CP-SMOKE-B execution NOT authorized
- `ClearancePostClient` NOT included in this release — next seam to implement
- CLI wire-up (`cli/main.py`) NOT included — deferred until all seams complete
- No real work_server, ports, DB, Docker, browser, Chrome, Xvfb, CDP, cookies, or live target used in tests; aiohttp in-process `TestClient` only
- CP2/session-clearance-pool out of scope and untouched

## [0.32.0] — 2026-08-26

### Added
- `RealClearanceObserver` in `cli/clearance_observer.py`: concrete `ClearanceObserver` seam for real clearance harness gates 12–13 (clearance observed, expires_at guard)
- All external interactions are injectable: `clearance_getter` (callable returning `ClearanceResult | None`; polled until `obtained=True` or timeout), `clock` (default: `time.monotonic`), `sleeper` (default: `time.sleep`) — no real browser, Chrome, Xvfb, CDP, cookies, server, network, or subprocess in tests
- `POLL_INTERVAL_SECONDS = 1.0` named module-level constant; exported for test assertions
- `observe(timeout_s)` behavior: polls `clearance_getter` in a deadline loop; treats both `None` and `ClearanceResult(obtained=False, ...)` as misses; `timeout_s=0` returns immediately without calling getter; returns `ClearanceResult(obtained=False, expires_at=None, clearance_class="")` on timeout
- `clearance_class` is always a label string (e.g. `"cf_clearance@fbref.com"`), never a raw cookie value; `scan_for_sensitive()` guard asserted directly in tests
- 11 synthetic unit tests in `tests/unit/cli/test_clearance_observer.py` covering timeout with getter always returning None, `timeout_s=0` short-circuit, timeout sentinel fields, first-call success, result pass-through, `expires_at` propagation, None-then-success with sleeper call count, `obtained=False` treated as miss, `POLL_INTERVAL_SECONDS` sleep value, and `scan_for_sensitive` safety on both success and timeout paths
- 3 harness integration tests confirming gate 12 (`clearance_observed`) blocks when observer returns `obtained=False`, gate 13 (`expires_at_guard`) blocks on expired `expires_at`, and gate 13 blocks on `expires_at` too far in the future

### Notes
- Real smoke NOT executed; `--real-clearance` remains blocked pending remaining seam implementations
- CP-SMOKE-B execution NOT authorized
- `RealClearanceObserver` is NOT wired into `cli/main.py` yet — wiring deferred until all seams are implemented
- Work-server clearance store bridge NOT included in this release (required before production wire-up; separate slice)
- No real browser, Chrome, Xvfb, CDP, cookies, server, network, subprocess, DB, Docker, or live target used in tests
- Remaining work before CLI wire-up: work-server clearance store bridge (`server.py`), `ClearancePostClient`
- CP2/session-clearance-pool out of scope and untouched

## [0.31.0] — 2026-08-25

### Added
- `RealBrowserLauncher` in `cli/browser_launcher.py`: concrete `BrowserLauncher` seam for real clearance harness gates 10–11 (browser startup and CDP readiness poll)
- All external interactions are injectable: `engine_starter` (async coroutine factory for engine startup), `cdp_probe` (async coroutine factory for CDP readiness check), `loop_runner` (sync-to-async bridge; default: `asyncio.run`), `clock` (monotonic clock; default: `time.monotonic`), `sleeper` (default: `time.sleep`) — no real Chrome, Xvfb, CDP, subprocess, or browser execution in tests
- `start() -> bool`: calls `loop_runner(engine_starter())`; returns `True` on success, `False` on any exception; sets internal started flag
- `wait_cdp_ready(timeout_s) -> tuple[bool, int]`: returns `(False, 0)` immediately if `start()` was not called or failed; otherwise polls `loop_runner(cdp_probe())` in a deadline loop; returns `(True, elapsed_s)` on first success; `(False, elapsed_s)` on timeout; elapsed is always non-negative
- 13 synthetic unit tests in `tests/unit/cli/test_browser_launcher.py` covering `start()` success/failure, `wait_cdp_ready()` early-return-on-not-started, immediate success with elapsed, timeout with one probe failure (deterministic via `_make_advancing_clock`), zero-timeout boundary, non-negative elapsed guarantee, and sleeper call count assertions
- 3 harness integration tests confirming gates 10 (`browser_startup`) and 11 (`cdp_ready`) block correctly on failed start and CDP timeout

### Notes
- Real smoke NOT executed; `--real-clearance` remains blocked pending remaining seam implementations
- CP-SMOKE-B execution NOT authorized
- `RealBrowserLauncher` is NOT wired into `cli/main.py` yet — wiring deferred until all seams are implemented
- No real Chrome, Xvfb, CDP, subprocess, browser, work_server, DB, Docker, or live target used in tests
- Remaining runtime-sensitive seams NOT included in this release: `ClearanceObserver`, `ClearancePostClient`
- CP2/session-clearance-pool out of scope and untouched

## [0.30.0] — 2026-08-25

### Added
- `RealWorkServerLifecycle` in `cli/work_server_lifecycle.py`: concrete `WorkServerLifecycle` seam for real clearance harness gates 7–9 (work server startup, health check, auth failure probe, shutdown)
- All external interactions are injectable: `process_starter`, `health_getter`, `clearance_poster`, `clock`, `sleeper` — no real server, ports, or subprocess execution in tests
- `startup(timeout_s)`: spawns server subprocess via injectable `process_starter`; polls `GET /health` via injectable `health_getter`/`clock`/`sleeper` until status 200 or timeout
- `health_check()`: returns `True` only for HTTP 200 + `{"status": "ok"}` body; `False` on any other response or exception
- `auth_failure_probe()`: POSTs to `/api/clearance` with fixed synthetic garbage token (`__smoke_probe__`) — never the real bearer token; returns HTTP status code; exceptions return 0
- `shutdown()`: terminates subprocess; waits up to 3 s; kills on `TimeoutExpired`; swallows all cleanup exceptions; no-op if no process is running
- 21 synthetic unit tests in `tests/unit/cli/test_work_server_lifecycle.py` covering startup timeout (deterministic via injected clock/sleeper), startup success, health check edge cases (non-dict body, missing `ok` status, JSON parse failure), auth probe header assertions (garbage token sent, real token NOT sent), and all shutdown paths (no-process, terminate+wait, kill-on-timeout, kill-raises)
- 3 harness integration tests confirming gates 7 (`work_server_startup`), 8 (`work_server_health`), and 9 (`auth_failure_probe`) block correctly on startup raise, health failure, and non-401 probe result

### Notes
- Real smoke NOT executed; `--real-clearance` remains blocked pending remaining seam implementations
- CP-SMOKE-B execution NOT authorized
- `RealWorkServerLifecycle` is NOT wired into `cli/main.py` yet — wiring deferred until all seams are implemented
- No real work server started; no ports bound; no subprocess, browser, DB, Docker, or live target used in tests
- Remaining runtime-sensitive seams NOT included in this release: `BrowserLauncher`, `ClearanceObserver`, `ClearancePostClient`
- CP2/session-clearance-pool out of scope and untouched

## [0.29.0] — 2026-08-25

### Added
- `GhCICheckProvider` in `cli/clearance_providers.py`: subprocess-based `CICheckProvider` for real clearance harness gate 3; executes `gh run list --json` via an injectable runner (production only — tests always inject synthetic JSON)
- Runs sorted by `createdAt` descending before evaluation; newest overall run drives the result: not-completed → BLOCKED, `conclusion != "success"` (including `null`) → BLOCKED, `conclusion == "success"` → ALL_PASS
- 19 unit tests in `tests/unit/cli/test_ci_check_provider.py` covering all BLOCKED paths (failure/cancelled/timed_out/action_required/in_progress/queued/empty/invalid JSON/non-zero exit/null conclusion), timestamp-ordering semantics, and gate-3 harness composition

### Fixed
- Strict mypy error: bare `dict` annotation replaced with `dict[str, str | None]`; sort lambda uses `or ""` to safely handle explicit `null` `createdAt` values (latent `TypeError` on null key fixed as a side effect)

### Notes
- Real smoke NOT executed; `--real-clearance` remains blocked pending remaining seam implementations
- CP-SMOKE-B execution NOT authorized
- Runtime-sensitive seams NOT included in this release: `WorkServerLifecycle`, `BrowserLauncher`, `ClearanceObserver`, `ClearancePostClient`
- CP2/session-clearance-pool out of scope and untouched

## [0.28.0] — 2026-08-25

### Added
- `cli/clearance_providers.py`: config-only implementations for `TargetProvider` (`EnvTargetProvider`), `TokenProvider` (`EnvTokenProvider`), `BrowserParameterProvider` (`EnvBrowserParameterProvider`), and `TargetValidator` (`LabelTargetValidator`) — reads env vars only; `source_class()` returns static label strings, never raw env values
- 26 unit tests in `tests/unit/cli/test_clearance_providers.py` covering `is_ready()` (set/empty/missing/whitespace-only), `source_class()` label-only assertions, `validate_against_allowlist()`, `LabelTargetValidator` exact-match (prefix/superset/placeholder rejected), and gate-1 harness composition

### Fixed
- Secret Scanning false positive: synthetic fixture value renamed in `test_source_class_never_exposes_token_value`
- `.gitleaksignore` fingerprint format corrected: inline `# comment` moved to separate preceding comment line; bare fingerprint now on its own line as required by gitleaks v8

### Notes
- Real smoke NOT executed; `--real-clearance` remains blocked at `provider_readiness`
- CP-SMOKE-B execution NOT authorized
- Runtime-sensitive providers/seams NOT included in this release: `CICheckProvider`, `WorkServerLifecycle`, `BrowserLauncher`, `ClearanceObserver`, `ClearancePostClient`
- CP2/session-clearance-pool out of scope and untouched

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

[Unreleased]: https://github.com/ChechiDev/sportcrawl/compare/v0.37.0...HEAD
[0.37.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.36.0...v0.37.0
[0.36.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.35.0...v0.36.0
[0.35.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.34.0...v0.35.0
[0.34.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.33.0...v0.34.0
[0.33.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.32.0...v0.33.0
[0.32.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.31.0...v0.32.0
[0.31.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.30.0...v0.31.0
[0.30.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.29.0...v0.30.0
[0.29.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.28.0...v0.29.0
[0.28.0]: https://github.com/ChechiDev/sportcrawl/compare/v0.27.0...v0.28.0
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
