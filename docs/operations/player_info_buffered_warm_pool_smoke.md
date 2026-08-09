# Player Info Buffered Warm-Pool — Smoke Validation Runbook

**Status:** Disabled by default. Requires explicit feature flags to enable.

**Feature flags:**

- `SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED=true` — activates buffered dispatch mode
- `SCRAPING__PLAYER_INFO_WARM_POOL_ENABLED=true` — activates warm browser pool (requires buffer enabled)

**Default behavior is unchanged.** With both flags absent or `false`, the scraper runs in direct mode exactly as before PR #142.

**This runbook does not claim live validation results.** No live scraping was run to produce this document. Stage 0 is the only stage executable without a live database.

---

## Purpose

This runbook provides a safe, staged smoke validation procedure for the
`player_info` buffered warm-pool execution path integrated in PR #142.

The three-mode matrix is:

| `dispatch_buffer_enabled` | `warm_pool_enabled` | Mode |
|---|---|---|
| `false` | (any) | **direct** — each worker calls `claim_next()` from PostgreSQL independently |
| `true` | `false` | **buffered** — `CandidateProducer` + `BoundedCandidateBuffer`; workers claim at handoff |
| `true` | `true` | **buffered + warm pool** — `WarmBrowserPool` owns the browser lifecycle per slot |

Modes are mutually exclusive at runtime. Setting both flags to `false` always returns to direct mode without code changes, database migrations, or destructive SQL.

---

## Relationship to existing soak runbook

`docs/operations/player_info_buffered_mode_soak.md` covers the buffered-only path
(`dispatch_buffer=true`, `warm_pool=false`) at higher worker counts (2–25 workers) for
stability soak testing. This runbook covers the warm-pool addition at conservatively
small scale (1–2 workers) and adds Stage 0 static verification. Complete the staged
validation here before attempting the larger-scale soak.

---

## Prerequisites

- A **local and disposable** PostgreSQL database. Do not use a production, remote,
  shared, or Oracle Cloud database for smoke validation.
- A known, bounded number of `player_info` candidates in PENDING state before startup.
  If population cannot be bounded, do not proceed past Stage 0.
- Direct read-only database access for queue inspection during the run.
- Ability to observe the Rich live display and structured logs in the terminal.
- Ability to send SIGTERM / Ctrl+C and confirm clean shutdown.
- `uv` installed and `uv run python scripts/scrape_player_info.py --workers N` working.
- Alembic revision `p57a` (or `p56a`) applied — the scraper verifies this at startup and
  will refuse to run if the revision is absent or incompatible.

---

## Local safety checklist

Before each stage:

- [ ] Confirm current branch/commit: `git log --oneline -1`
- [ ] Working tree is clean: `git status --short`
- [ ] Database is local and disposable (not production, not shared)
- [ ] Candidate population is bounded and known before startup
- [ ] No other scraper process is running against the same database
- [ ] You can kill the process and confirm it exits cleanly

---

## DB safety checklist

Before each stage, run a read-only snapshot:

```sql
BEGIN TRANSACTION READ ONLY;

-- Queue counts by status before run
SELECT status, count(*)
FROM sch_fbref_infra.scrape_queue
WHERE job_type = 'player_info'
GROUP BY status
ORDER BY status;

-- Oldest pending candidate age
SELECT min(created_at) AS oldest_pending
FROM sch_fbref_infra.scrape_queue
WHERE job_type = 'player_info' AND status = 'PENDING';

-- Already-processed player info count
SELECT count(*) AS already_done
FROM sch_fbref_shared.tbl_player_info;

ROLLBACK;
```

Record these baseline counts. Compare after each stage.

---

## Environment variables and defaults

All variables use the `SCRAPING__` prefix and can be set inline or via `.env`.

**Mode flags (both default to `false`):**

| Variable | Default | Notes |
|---|---|---|
| `SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED` | `false` | Must be `true` for buffered and warm-pool modes |
| `SCRAPING__PLAYER_INFO_WARM_POOL_ENABLED` | `false` | Has no effect unless buffer is also enabled |

**Buffer configuration:**

| Variable | Default | Notes |
|---|---|---|
| `SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_SIZE` | `20` | Max candidate refs held in memory at once |
| `SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_PREFETCH` | `50` | How many PENDING IDs the producer peeks per batch |
| `SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_POLL_INTERVAL` | `5.0` | Seconds between producer poll cycles when queue is empty |

**Rate-limit gate configuration:**

| Variable | Default | Notes |
|---|---|---|
| `SCRAPING__PLAYER_INFO_GATE_COOLDOWN_SECS` | `60.0` | Seconds to wait after a rate-limit signal before probing |
| `SCRAPING__PLAYER_INFO_GATE_PROBE_TIMEOUT_SECS` | `30.0` | Per-probe timeout |
| `SCRAPING__PLAYER_INFO_GATE_MAX_PROBE_ATTEMPTS` | `3` | Max consecutive probe failures before gate stays closed |

**Warm pool configuration:**

| Variable | Default | Notes |
|---|---|---|
| `SCRAPING__PLAYER_INFO_POOL_BROWSER_START_CONCURRENCY` | `1` | Max slots starting a browser in parallel (keep at 1 for smoke) |
| `SCRAPING__PLAYER_INFO_POOL_WARMUP_CONCURRENCY` | `1` | Max slots warming up in parallel (keep at 1 for smoke) |
| `SCRAPING__PLAYER_INFO_POOL_STARTUP_JITTER_MIN` | `2.0` | Min startup jitter seconds per slot |
| `SCRAPING__PLAYER_INFO_POOL_STARTUP_JITTER_MAX` | `15.0` | Max startup jitter seconds per slot |
| `SCRAPING__PLAYER_INFO_POOL_BROWSER_BACKOFF_BASE` | `2.0` | Browser failure backoff base seconds |
| `SCRAPING__PLAYER_INFO_POOL_BROWSER_BACKOFF_MAX` | `120.0` | Browser failure backoff cap |
| `SCRAPING__PLAYER_INFO_POOL_TASK_BACKOFF_BASE` | `2.0` | Task restart backoff base seconds |
| `SCRAPING__PLAYER_INFO_POOL_TASK_BACKOFF_MAX` | `60.0` | Task restart backoff cap |

> **Note:** The warm pool creates one slot per `--workers N` argument. The number of pool
> slots equals the number of workers. `SCRAPING__PLAYER_INFO_POOL_SIZE` is declared in
> settings but the pool size is driven by the `--workers` CLI flag at runtime.

---

## CLI entry point

```
uv run python scripts/scrape_player_info.py --workers N
```

`N` must be between 1 and 25 (inclusive). Default is 1.

The scraper runs the Alembic version check, stale recovery, and startup drain on every
invocation regardless of mode. It then launches the selected mode.

---

## Stage 0 — Static verification (no live database required)

Verify the implementation before any runtime.

### 0.1 Confirm flags default to `false`

```bash
python3 -c "
from config.settings import ScrapingSettings
s = ScrapingSettings()
assert s.player_info_dispatch_buffer_enabled is False, 'buffer not disabled by default'
assert s.player_info_warm_pool_enabled is False, 'warm_pool not disabled by default'
print('Stage 0.1 PASS: both flags default to false')
"
```

### 0.2 Mode-selection log lines (suppressed at default log level)

The script emits a mode-selection log line at startup, but at `INFO` level. The script
root logger is hardcoded to `WARNING`, so **none of the mode-selection lines appear in
the terminal output by default** — including the direct-mode line.

Mode-selection messages (all at INFO level, all suppressed at WARNING threshold):

| Mode | Log line format |
|---|---|
| Direct | `player_info: direct mode \| workers=N` |
| Buffered only | `player_info: buffered mode \| workers=N \| buffer_size=M \| gate_cooldown=Xs` |
| Buffered + warm pool | `player_info: buffered+warm_pool mode \| workers=N \| buffer_size=M \| gate_cooldown=Xs` |

**To confirm the selected mode without relying on log output, verify the environment
variables directly before starting the process:**

```bash
echo "BUFFER: ${SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED:-false}"
echo "WARM_POOL: ${SCRAPING__PLAYER_INFO_WARM_POOL_ENABLED:-false}"
```

### 0.3 Confirm flag defaults

### 0.4 Confirm rollback path is flag-only


The rollback procedure requires only unsetting or setting variables to `false`. It does
not require code changes, database migrations, or destructive SQL. Verify this is the
case by confirming no default-enabling code exists:

```bash
grep -rn "player_info_dispatch_buffer_enabled\s*=\s*True\|player_info_warm_pool_enabled\s*=\s*True" \
  config/ scripts/ infrastructure/ core/ ports/ cli/
```

Expected output: no matches (the only `True` occurrences should be in tests or
environment-variable overrides, never in default declarations).

### 0.5 Stage 0 pass criteria

- Both flags default to `false` ✓
- Mode-selection log lines documented (suppressed by default; use env var inspection instead) ✓
- No code path enables warm-pool or buffer by default ✓

---

## Stage 1 — Direct mode baseline

Run the existing stable direct mode to establish a clean baseline before testing
experimental flags. This stage uses no experimental features.

**Maximum scope: 1 worker, 1–3 controlled candidates.**

```bash
uv run python scripts/scrape_player_info.py --workers 1
```

No extra environment variables. Default direct mode.

### Expected startup sequence

1. Alembic version check passes.
2. `recover_all_stale()` resets any lingering IN_PROGRESS rows (logs count if nonzero).
3. `_startup_drain()` inserts or reactivates due candidates (logs total scheduled).
4. Worker starts, claims jobs directly from PostgreSQL.

### Expected DB state before

- N candidates in PENDING
- 0 candidates in IN_PROGRESS (startup recovery handles any stale rows)

### Expected DB state during

- 1 candidate moves to IN_PROGRESS while being processed
- Completed candidates transition to DONE

### Expected DB state after clean stop (Ctrl+C / SIGTERM)

- Any IN_PROGRESS row at time of stop remains IN_PROGRESS (recovered at next startup)
- DONE rows from this run remain DONE
- PENDING rows that were not yet claimed remain PENDING

### Expected DB state after interrupted stop and restart

- The next startup calls `recover_all_stale()`, which resets IN_PROGRESS → PENDING
- `_startup_drain()` re-populates any newly-due candidates

### Rollback

Stop the process (Ctrl+C). No flags to unset — direct mode is the default. No DB changes needed.

### Stop conditions at Stage 1

Stop immediately if:

- Any candidate is processed that was not in the bounded candidate set
- FATAL error appears: `FATAL: cannot record failure`
- Browser starts fail repeatedly (more than 3 restarts within 5 minutes)
- Unexpected duplicate processing (same player written twice)
- Queue state becomes inconsistent

---

## Stage 2 — Buffered mode without warm pool

Enable dispatch buffer only. Keep warm pool disabled. Use 1–2 workers.

**Maximum scope: 2 workers, tiny bounded candidate set.**

```bash
SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED=true \
  uv run python scripts/scrape_player_info.py --workers 2
```

### What changes from Stage 1

- `CandidateProducer` starts as a background task named `dispatch-producer`.
- It peeks PENDING job IDs (no claim, no lock) and fills a `BoundedCandidateBuffer`.
- Workers consume job references from the buffer and claim from PostgreSQL at handoff.
- A `RateLimitGate` is created and wired to the producer (gate pause on rate-limit signal).
- After each worker's browser warms up successfully, that worker calls `gate.mark_engine_ready()`
  (reopens the gate). This is the buffered-without-pool path — in Stage 3 this is handled by
  the pool's `on_warmup_success` callback instead.
- Direct `claim_next()` per worker is disabled.

### Expected startup sequence

1. Alembic check, stale recovery, startup drain (same as Stage 1).
2. `CandidateProducer` begins polling for PENDING IDs.
3. Workers block on `buffer.get()` until a candidate reference is available.
4. On each handoff: worker claims the job by ID (`claim_by_id`), processes, commits.

### Expected observable log events (WARNING level and above)

These events appear in the Rich live display widget:

- Browser restart: `WARNING  Browser start failed — retry N/M`
- Gate closed on rate-limit: `rate_limit_gate: CLOSED | reason=rate_limit_429` (WARNING)
- Gate probe timeout: `rate_limit_gate: probe TIMEOUT (attempt N/M)` (WARNING)
- Gate probe exception: `rate_limit_gate: probe EXCEPTION (attempt N/M): ExcType` (WARNING)
- Gate probe failure: `rate_limit_gate: probe FAILED (attempt N/M)` (WARNING)
- Gate stuck closed: `rate_limit_gate: all N probes failed — gate remains CLOSED` (ERROR)

### Expected DB state

Same as Stage 1, plus:
- Claim-at-handoff means no long DB lock is held while the buffer is being filled
- A race loss (another process claimed the job first) is safe and logged at DEBUG:
  `dispatch: job N already claimed, skipping`

### Invariants to verify

- [ ] No IN_PROGRESS job sits unassigned in memory (claim happens immediately at handoff)
- [ ] No DB transaction remains open while waiting on buffer capacity
- [ ] Gate closure pauses producer; producer resumes only after gate reopens
- [ ] Candidate buffer contains only integer job IDs (no HTML, no URLs, no credentials)

### Stop conditions at Stage 2

Same as Stage 1, plus:

- Gate closes 3+ times within 5 minutes → stop, investigate rate-limit behavior
- `rate_limit_gate: all N probes failed` → gate stuck closed → stop
- Producer appears to busy-spin (buffer.get() loops without blocking) → stop

### Rollback

Stop the process (Ctrl+C). Remove or set to `false`:

```bash
unset SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED
```

Restart without the flag. Direct mode resumes immediately. No DB changes needed.

---

## Stage 3 — Buffered + warm-pool smoke

Enable both flags. Use 1–2 workers. This is the primary new path integrated in PR #142.

**Maximum scope: 2 workers, tiny bounded candidate set.**

```bash
SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED=true \
SCRAPING__PLAYER_INFO_WARM_POOL_ENABLED=true \
  uv run python scripts/scrape_player_info.py --workers 2
```

### What changes from Stage 2

- `WarmBrowserPool` is created with 2 slots (one per `--workers` count).
- Each slot independently starts its own `PydollEngine`, calls `engine.start()` then
  `engine.warmup(fbref_base_url)`.
- After warmup succeeds, the slot calls `on_warmup_success` = `gate.mark_engine_ready()`,
  which opens the `RateLimitGate` for production work.
- The slot then enters `claim_loop_fn(engine)` = `_run_buffered_loop(engine, buffer)`.
- `asyncio.gather(...)` per-worker is replaced by `_warm_pool.run()`.
- Slots are supervised: on task failure (`CooldownRequired` → returns `-1`), the slot
  closes the current engine in its `finally` block, waits `task_backoff`, then creates a
  fresh engine on the next iteration.
- The `finally` block always fires `on_engine_teardown` = `gate.cancel_recovery()` on
  every engine exit — whether the exit is a clean `-1` return, a browser exception, or
  a `CancelledError` on shutdown. This is intentional: `cancel_recovery()` prevents a
  dead engine's probe from exhausting attempts and leaving the gate permanently closed.
- On shutdown: `_warm_pool.shutdown()` cancels all slot tasks; `_gate.shutdown()`
  cancels any in-flight recovery task.

### Expected observable log events

All Stage 2 observable events apply here, plus:

- Slot task restart: `[slot-N] claim loop requested restart; backoff Xs` (WARNING)
  — emitted by `WorkerSlot` when `claim_loop_fn` returns `-1` (e.g. on `CooldownRequired`)
- Slot browser failure: `[slot-N] browser error (ExcType); backoff Xs` (WARNING)
  — emitted on exception in engine start or warmup

All gate log levels for reference:

| Log message | Level |
|---|---|
| `rate_limit_gate: CLOSED \| reason=...` | WARNING |
| `rate_limit_gate: probe TIMEOUT (attempt N/M)` | WARNING |
| `rate_limit_gate: probe EXCEPTION (attempt N/M): ExcType` | WARNING |
| `rate_limit_gate: probe FAILED (attempt N/M)` | WARNING |
| `rate_limit_gate: all N probes failed — gate remains CLOSED` | **ERROR** |
| `rate_limit_gate: cooldown started (Xs)` | INFO (suppressed at default threshold) |
| `rate_limit_gate: cooldown complete` | INFO (suppressed) |
| `rate_limit_gate: REOPENED ...` | INFO (suppressed) |
| `rate_limit_gate: recovery task cancelled` | DEBUG (suppressed) |
| `rate_limit_gate: shutdown...` | DEBUG (suppressed) |

### RateLimitGate lifecycle in warm-pool mode

1. Gate starts **open**.
2. First engine to warm up calls `mark_engine_ready()` (idempotent if already open).
3. If a worker catches `RateLimitError`: `signal_rate_limit()` closes the gate and
   schedules a cooldown + probe recovery task.
4. When the engine is torn down: `cancel_recovery()` cancels the stale probe task.
   Gate remains **closed**.
5. When a new engine finishes warmup: `mark_engine_ready()` reopens the gate.
6. Producer pauses at `wait_if_closed()` while gate is closed.
7. On clean shutdown: `gate.shutdown()` cancels any in-flight recovery task.

### Expected DB state before

- N candidates in PENDING (same as Stages 1–2)
- 0 candidates in IN_PROGRESS

### Expected DB state during

- Up to 2 candidates in IN_PROGRESS simultaneously (one per worker slot)
- Completed candidates transition to DONE
- Claim-at-handoff: no IN_PROGRESS row sits unassigned while the buffer waits

### Expected DB state after clean stop

- Same recovery pattern as Stages 1–2: IN_PROGRESS rows at time of stop are reset at
  next startup via `recover_all_stale()`

### Invariants to verify at Stage 3

- [ ] `WarmBrowserPool` log lines appear before any claim activity starts
- [ ] Both slots independently warm up before consuming from the buffer
- [ ] Gate does not open until at least one slot completes warmup
- [ ] On slot task restart (`-1` return), the engine is closed and a fresh engine starts
- [ ] On clean shutdown, all slots and the gate recovery task terminate without hanging
- [ ] No per-worker direct `claim_next()` call is active (no direct-mode DB claims)
- [ ] `CandidateProducer` stops and the producer task completes on shutdown

### Stop conditions at Stage 3

Same as Stage 2, plus:

- Warm-pool slots repeatedly restart (more than 3 browser restarts per slot in 5 minutes)
- Graceful shutdown hangs (pool or producer task does not exit within 30 seconds)
- Browser or Chrome child processes remain after process exit: `pgrep -a chrome`
- Sensitive information appears in logs (see "What not to capture" below)
- Unexpected HTTP 403, 429, or Cloudflare challenge responses

### Rollback

Stop the process (Ctrl+C). Unset both flags:

```bash
unset SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED
unset SCRAPING__PLAYER_INFO_WARM_POOL_ENABLED
```

Restart without flags. Direct mode resumes. No code changes, migrations, or destructive
SQL required.

---

## Stage 4 — Optional cautious expansion

Only proceed if Stages 1–3 were clean and stable.

**Maximum scope in this runbook: 5 workers.**

Do not scale to 10, 15, or 25 workers in this runbook. A separate soak runbook
(`docs/operations/player_info_buffered_mode_soak.md`) covers higher worker counts for
the buffered-only path. A separate future soak phase should be planned for
warm-pool mode at larger scale, with dedicated stop criteria and duration requirements.

```bash
SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED=true \
SCRAPING__PLAYER_INFO_WARM_POOL_ENABLED=true \
  uv run python scripts/scrape_player_info.py --workers 5
```

Stop criteria and rollback are the same as Stage 3.

---

## Required invariants (all stages)

| Invariant | How to verify |
|---|---|
| Direct and buffered modes are mutually exclusive | Check mode-selection env vars; only one active code path runs |
| Buffer contains only unclaimed PENDING references | No claim or lock is held during buffer fill; claim happens at handoff only |
| Claim happens only at handoff to a ready worker | No IN_PROGRESS job sits unassigned in memory |
| No DB transaction open while waiting on buffer capacity | Each `claim_by_id` session opens, commits, and closes immediately |
| PostgreSQL is the durable source of truth | All job state transitions persist in `sch_fbref_infra.scrape_queue` |
| Gate closure pauses producer | `CandidateProducer` calls `wait_if_closed()` at each fill cycle |
| Gate reopens only after readiness/warmup succeeds | `mark_engine_ready()` is called only from `on_warmup_success` callback |
| Buffered/warm-pool path is disabled by default | Both flags default to `false`; no code path enables them implicitly |
| Rollback = unset flags, no DB changes needed | Verified in Stage 0.4 and rollback sections above |

---

## DB inspection during a run (read-only)

Use a read-only transaction for all inspection. Do not run `UPDATE`, `DELETE`,
`INSERT`, `TRUNCATE`, `SELECT ... FOR UPDATE`, advisory locks, or migration commands.

```sql
BEGIN TRANSACTION READ ONLY;

-- Queue status distribution
SELECT status, count(*)
FROM sch_fbref_infra.scrape_queue
WHERE job_type = 'player_info'
GROUP BY status
ORDER BY status;

-- Retry count distribution
SELECT retry_count, count(*)
FROM sch_fbref_infra.scrape_queue
WHERE job_type = 'player_info'
GROUP BY retry_count
ORDER BY retry_count;

-- In-progress count (should not exceed worker count)
SELECT count(*) AS in_progress_count
FROM sch_fbref_infra.scrape_queue
WHERE job_type = 'player_info' AND status = 'IN_PROGRESS';

-- Failed count and oldest failure
SELECT count(*) AS failed_count, min(updated_at) AS oldest_failure
FROM sch_fbref_infra.scrape_queue
WHERE job_type = 'player_info' AND status = 'FAILED';

-- Total player info rows written
SELECT count(*) AS player_info_written
FROM sch_fbref_shared.tbl_player_info;

ROLLBACK;
```

---

## Evidence to capture

After each stage, record:

- Git commit SHA: `git log --oneline -1`
- Command used (variable names and values, not secrets)
- Worker count
- Buffer size (default 20 unless overridden)
- Start time and stop time
- Number of candidates processed (from process exit output)
- Queue counts by status before and after (from read-only SQL above)
- Number of slot restarts visible in logs (`[slot-N] claim loop requested restart`)
- Number of browser failures visible in logs (`[slot-N] browser error`)
- Number of gate closures (`rate_limit_gate: CLOSED`) if any occurred
- Number of gate probe failures if any occurred
- Whether shutdown completed cleanly (no hanging tasks)
- Final `git status --short`
- Final `pgrep -a chrome` output (should be empty after process exits)

---

## What not to capture

Do not log, record, screenshot, or commit:

- Cookies or cookie values
- CDP tokens or WebSocket URLs (`ws://`, `wss://`)
- Browser session payloads or CDP state
- Raw HTML responses
- Credentials or secrets
- Full browser profile directory paths
- Raw queue payloads
- Full player URLs
- Complete database connection strings or DSNs
- Any content from `SCRAPING__WORK_SERVER_TOKEN` or `DB__PASSWORD`

---

## Failure triage

| Symptom | Likely cause | Action |
|---|---|---|
| Scraper refuses to start | Alembic revision not p56a/p57a | Run `uv run alembic upgrade p57a` |
| `rate_limit_gate: all N probes failed` | Sustained rate-limit; probe engine can't warm up | Stop; investigate request frequency; increase `GATE_COOLDOWN_SECS` |
| `[slot-N] claim loop requested restart` repeated | `CooldownRequired` raised repeatedly | Stop; investigate failure pattern in queue (FAILED count) |
| `[slot-N] browser error` repeated | Chrome failing to start or crashing | Stop; check Chrome availability; check profile directory permissions |
| IN_PROGRESS count exceeds worker count | A previous run crashed without recovery | Next startup calls `recover_all_stale()` automatically; or check manually |
| Producer busy-spins | Buffer full while workers are slow | Check worker processing rate; reduce buffer size or worker count |
| Shutdown hangs | Pool or producer task blocked | Send SIGKILL as last resort; investigate on next run |
| `FATAL: cannot record failure` | DB connectivity lost during failure recording | Stop immediately; investigate DB connection |

---

## Abort conditions

Stop immediately if any of the following occur:

- Database is not proven local and disposable
- Candidate population is not bounded before startup
- More jobs begin processing than the bounded candidate set
- A candidate is claimed before worker handoff (direct claim in buffered mode)
- Duplicate processing observed (same player_id inserted twice)
- Producer or buffer appears to busy-spin without blocking
- Gate wait appears to busy-spin (workers not blocking on closed gate)
- Browser slots restart more than 3 times per slot in a 5-minute window
- Graceful shutdown hangs beyond 30 seconds
- Browser or Chrome child processes remain after process exit
- Sensitive information appears in logs (see "What not to capture")
- Repeated HTTP 403, 429, Cloudflare, or challenge responses within a single run
- Queue state becomes inconsistent (e.g., DONE count decreases)
- Destructive SQL would be required to recover

---

## Rollback procedure (any stage)

To return to direct mode at any time:

1. Stop the running process: Ctrl+C or SIGTERM.
2. Unset or set to `false`:
   ```bash
   unset SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED
   unset SCRAPING__PLAYER_INFO_WARM_POOL_ENABLED
   ```
   Or in `.env`:
   ```
   SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED=false
   SCRAPING__PLAYER_INFO_WARM_POOL_ENABLED=false
   ```
3. Restart the scraper normally:
   ```bash
   uv run python scripts/scrape_player_info.py --workers 1
   ```

Rollback requires no code changes, no database migrations, and no destructive SQL.
Any IN_PROGRESS rows at the time of stop are automatically recovered at the next startup
via `recover_all_stale()`.

Do not manually update or delete rows in `sch_fbref_infra.scrape_queue` unless
using a documented recovery operation (`recover_all_stale`, `recover_failed`).

---

## Security notes

- Buffered and warm-pool modes do not log cookies, CDP tokens, WebSocket URLs, or
  browser session data.
- The candidate buffer contains only integer job IDs.
- Gate logs contain only reason codes and timing information.
- The readiness probe only reports pass/fail; no HTML or session content is logged.
- `WorkerSlot` and `WarmBrowserPool` have no imports from `config` or `infrastructure.persistence`.
  This is enforced by the `lint-imports` contract.

---

## Live validation status

**Validation complete. All phases PASS.**

Live end-to-end validation was executed against an isolated PostgreSQL smoke environment
(Docker container, `127.0.0.1:15432`, run_id=`gate-a-20260809T171510Z-9364-38542daffed250a6`).
No production database was touched at any point during the validation run.

### Checkpoint summary

| Checkpoint | Phases | Result |
|---|---|---|
| CHECKPOINT 1 — execution modes | D3 (direct) + E4 (buffered) + F3 (buffered+warm-pool) | ✅ PASS |
| CHECKPOINT 2 — scalability characterization | G0–G7 (fake workers, 5/10/25/50 concurrency) | ✅ PASS |
| CHECKPOINT 3 — interruption and recovery | H0–H4 + H-REPAIR (SIGKILL + recover_all_stale) | ✅ PASS |

### Phase summary

| Phase range | Description | Result |
|---|---|---|
| A0–A3 | Gate A: isolated PostgreSQL container, schema verified | PASS |
| B0–B3 | Alembic migrations applied to smoke DB | PASS |
| C0–C3 | Controlled candidate seeded (Lionel Messi, player_id=`d70ce98e`) | PASS |
| D0–D3 | Direct mode: workers=1, buffer=OFF, warm_pool=OFF | PASS |
| E0–E4 | Buffered mode: workers=2, buffer=ON, warm_pool=OFF | PASS |
| F0–F3 | Buffered+warm-pool: workers=2, buffer=ON, warm_pool=ON | PASS |
| G0–G7 | Fake-worker concurrency characterization at 5/10/25/50 workers | PASS |
| H0–H4 + H-REPAIR | Controlled SIGKILL interruption and recovery validation | PASS |
| I0–I1 | Real-source soak: 3 candidates, direct mode, workers=2 | PASS |
| J0–J3 | Evidence consolidation, correctness matrix, operational conclusions | PASS |

### H-REPAIR: process-group kill strategy

During Phase H, a critical discovery changed the interruption procedure:

`uv run python` spawns Python as a child process of the `uv` supervisor. Sending SIGKILL
to the `uv` PID leaves the Python process as an orphan — it continues running and the
test never validates actual interruption. The correct strategy is to kill the entire
process group using `start_new_session=True` and `os.killpg`.

**Kill-at-PENDING rationale:** The kill must be issued immediately upon the drain creating
a PENDING row, not after IN_PROGRESS detection. Chrome profile warm-up and CDN-cached
FBRef responses reduce processing time to under 200ms — waiting for IN_PROGRESS detection
is a race the test consistently loses. Killing at PENDING is the reliable gate.

H1-R (`recover_all_stale` after process-group SIGKILL, PENDING state) and H2-R (restart
from PENDING, job completes at t+17s) both passed after H-REPAIR.

### Phase I real-source soak

Three real candidates were scraped against FBRef using direct mode (workers=2, no buffer,
no warm pool):

| Candidate | player_id |
|---|---|
| Lionel Messi | `d70ce98e` |
| Cristiano Ronaldo | `dea698d9` |
| Erling Haaland | `1f44ac21` |

All 3 jobs completed with status DONE and real FBRef data written to `tbl_player_info`.

Note: The post-soak verification script contained a minor asyncpg bug (unused parameter
causing `IndeterminateDatatypeError`). The soak itself was durable and clean; the bug
was in the verification query only, not in the scraping pipeline.

### Schema gotchas discovered during validation

The following schema details are non-obvious and must be respected in future tooling and queries:

- `tbl_player_info` lives in `sch_fbref_shared`, **not** `sch_fbref_backend`
- The `scrape_queue` row lock column is `locked_at`, **not** `claimed_at`
- The `tbl_player_urls` FK column is `fk_player`, **not** `fk_player_id`
- `tbl_players.career_start` and `career_end` are `NOT NULL` — any reset script must provide values
- Drain eligibility filter: `url_type='profile'`, `status IN ('PENDING','ACTIVE')`, `next_scrape_at <= now()`
- After a successful scrape: `tbl_player_urls.next_scrape_at` is advanced by `cadence_hours` (168h). Any
  test reset that manipulates this column must restore it to a value in the past to re-trigger drain eligibility.

### What not to capture

This document does not and must not contain:

- Database passwords, DSNs, or connection strings
- `SCRAPING__WORK_SERVER_TOKEN` or any other secret value
- CDP tokens, WebSocket URLs, browser session data, or cookies
- Browser profile paths or ephemeral volume names
- Raw HTML responses or scraped page content
- Any value that identifies a specific operator environment
