# Player Info Buffered Mode — Manual Soak Procedure

**Status:** Disabled by default. Requires explicit feature flag to enable.

**Feature flag:** `SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED=true`

Do not enable in production without completing this soak procedure.

---

## Prerequisites

- A local or staging environment with a populated `scrape_queue` (player_info jobs in PENDING state).
- Direct database access to observe queue state during the soak.
- Ability to observe structured logs and process metrics (memory, file descriptors).
- The ability to terminate the process and re-run it with different settings.

## What buffered mode changes

When `SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED=true`:

- A `CandidateProducer` fills an in-memory `BoundedCandidateBuffer` with PENDING job IDs (no claim, no lock).
- Workers consume job references from the buffer and claim the job from PostgreSQL at handoff.
- A `RateLimitGate` closes on `RateLimitError`, runs a bounded cooldown, and probes readiness before reopening.
- Direct PostgreSQL claiming by workers is disabled while buffered mode is active.
- The warm browser pool (`SCRAPING__PLAYER_INFO_WARM_POOL_ENABLED`) remains off by default and is separate from buffered mode.

When `SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED=false` (default):

- Direct claim mode is active. Workers call `claim_next()` directly from PostgreSQL.
- The buffer, producer, and rate-limit gate are not started.
- Existing behavior is fully preserved.

---

## Rollback

To return to direct mode at any time:

1. Stop the running process (Ctrl+C or SIGTERM).
2. Remove or set `SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED=false`.
3. Restart the process normally.

Do not manually edit the scrape_queue table unless using a documented recovery operation (`recover_all_stale`, `recover_failed`).

---

## Soak Procedure

### Stage 1 — 2 workers

```bash
SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED=true \
  uv run python scripts/scrape_player_info.py --workers 2
```

Run for at least 15 minutes. Record:

- Throughput (jobs/minute from log output)
- Failure count and retry count (from queue: `SELECT status, count(*) FROM scrape_queue WHERE job_type='player_info' GROUP BY status`)
- Browser restart count (from logs: `WARNING  Browser start failed`)
- Rate-limit gate events (from logs: `rate_limit_gate: CLOSED` / `REOPENED`)
- Cooldown events (from logs: `cooldown started` / `cooldown complete`)
- Readiness probe results (from logs: `probe passed` / `probe FAILED`)
- Memory (RSS): `ps -o rss= -p <PID>` or equivalent
- Open file descriptors: `ls /proc/<PID>/fd | wc -l` or `lsof -p <PID> | wc -l`
- DB queue state: pending/in_progress/done/failed row counts

**Stop criteria at this stage:**
- Any repeated `rate_limit_gate: all N probes failed` message within 15 minutes → stop, investigate.
- Memory growing >500 MB above baseline without recovery → stop.
- File descriptor count growing continuously → stop.
- `FATAL: cannot record failure` error → stop immediately.
- Unexpected duplicate processing (same player_id inserted twice) → stop, investigate.

### Stage 2 — 5 workers

Only proceed if Stage 1 was stable for at least 15 minutes.

```bash
SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED=true \
  uv run python scripts/scrape_player_info.py --workers 5
```

Run for at least 20 minutes. Record the same metrics as Stage 1.

**Stop criteria:** Same as Stage 1.

### Stage 3 — 10 workers

Only proceed if Stage 2 was stable.

```bash
SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED=true \
  uv run python scripts/scrape_player_info.py --workers 10
```

Run for at least 20 minutes. Record the same metrics.

Watch especially for:
- Increased `claim_by_id` misses (logged as `dispatch: job N already claimed, skipping`): a moderate rate is expected and safe.
- DB lock contention: monitor `pg_stat_activity` for long-running lock waits.

**Stop criteria:** Same as Stage 1. Also stop if DB lock waits exceed 10 seconds.

### Stage 4 — 15 workers

Only proceed if Stage 3 was stable.

```bash
SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED=true \
  uv run python scripts/scrape_player_info.py --workers 15
```

Run for at least 30 minutes. Record the same metrics.

**Stop criteria:** Same as above.

### Stage 5 — up to 25 workers (only if Stage 4 is stable)

Only proceed if Stage 4 was stable for at least 30 minutes with no stop criteria triggered.

```bash
SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED=true \
  uv run python scripts/scrape_player_info.py --workers 25
```

Run for at least 30 minutes. Record the same metrics.

---

## Stop Criteria (all stages)

Stop immediately if ANY of these occur:

- Repeated `rate_limit_gate: CLOSED` within a 5-minute window (3 or more closures)
- `rate_limit_gate: all N probes failed` → gate stuck closed
- Repeated readiness probe failures (`probe FAILED` ≥ 5 consecutive)
- Rising FAILED or STALE job count in the queue without recovery
- Memory (RSS) growing continuously for more than 10 minutes without recovery
- File descriptor count growing continuously for more than 10 minutes
- Browser restart storm: more than 5 restarts per worker per 10-minute window
- DB lock contention exceeding 10s
- Unexpected duplicate processing (same player written twice)
- `FATAL: cannot record failure` in any log

## What to record at each stage

For each stage, save a snapshot of:

```sql
-- Queue state
SELECT status, count(*) FROM sch_fbref_infra.scrape_queue
WHERE job_type = 'player_info' GROUP BY status;

-- Retry distribution
SELECT retry_count, count(*) FROM sch_fbref_infra.scrape_queue
WHERE job_type = 'player_info' GROUP BY retry_count ORDER BY retry_count;
```

And from logs:
- Count of `rate_limit_gate: CLOSED` events
- Count of `rate_limit_gate: REOPENED` events
- Count of `probe passed` vs `probe FAILED` events
- Count of `released job N to PENDING (gate closed)` events
- Count of `already claimed, skipping` events (claim race misses)

---

## Security notes

- Buffered mode does not log cookies, CDP tokens, WebSocket URLs, or browser session data.
- The candidate buffer contains only integer job IDs.
- Gate logs contain only reason codes and timing information.
- The readiness probe only reports pass/fail — no HTML or session content is logged.

---

## Notes

- Do not commit soak result logs to the repository.
- Do not scale beyond 25 workers — the UI and settings enforce a maximum of 25.
- If in doubt at any stage, roll back to direct mode and investigate before continuing.
