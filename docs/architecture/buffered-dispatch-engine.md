# Buffered Dispatch Engine — Architecture Decision

**Status:** Decided  
**Date:** 2026-08-09  
**Validated by:** E2E smoke run, Phases A0–J3

---

## Decision summary

The buffering and warm-pool execution model validated through `player_info` (PR #142) must
be treated as a **shared, always-active dispatch runtime**, not as a `player_info`-specific
feature and not as a per-scraper duplicated subsystem.

A single dispatch engine runs at the top of the scraping runtime. Different workloads
attach to it via per-workload policy objects. The engine itself is workload-agnostic;
the policy object carries all workload-specific behavior.

This eliminates the risk of N independent buffering implementations drifting apart and
prevents the accidental growth of parallel buffering stacks as new scraping domains are added.

---

## Validation evidence

| Phase | What was validated |
|---|---|
| D3 | Direct mode baseline: workers=1, no buffer, no warm pool. Job reaches DONE via the standard claim→process→write path. |
| E4 | Buffered mode: workers=2, buffer=ON, warm pool=OFF. `BoundedCandidateBuffer` drains correctly; no starvation, no deadlock. |
| F3 | Buffered+warm-pool: workers=2, buffer=ON, warm pool=ON. `WarmBrowserPool` and `WorkerSlot` coordinate without contention. |
| G0–G7 | Fake-worker scalability characterization at 5, 10, 25, and 50 concurrent workers. Claim throughput measured; no queue corruption observed. |
| H1–H4 + H-REPAIR | Controlled SIGKILL interruption (full process group via `os.killpg`). `recover_all_stale()` correctly resets IN_PROGRESS and PENDING rows. Jobs restart cleanly on the next run. |
| I1 | Real-source soak: 3 candidates scraped from FBRef in direct mode with workers=2. All 3 jobs completed DONE with real data written to `tbl_player_info`. |

---

## Target architecture

One shared dispatch engine instance per scraping runtime process. Each workload registers
a **policy object** that carries all workload-specific configuration:

```
WorkloadPolicy:
  job_type                # scrape_queue job_type discriminator
  candidate_source        # query or repository method that produces candidate IDs
  claim_strategy          # how rows are claimed (SELECT FOR UPDATE SKIP LOCKED, etc.)
  processor_adapter       # callable that maps a candidate ID to a scrape execution
  concurrency_limit       # max simultaneous in-flight jobs for this workload
  buffer_size             # BoundedCandidateBuffer capacity
  pool_size               # WarmBrowserPool slot count
  retry_backoff           # BackoffPolicy instance for claim and warmup failures
  recovery_contract       # which stale states to reset at startup (IN_PROGRESS, ACTIVE)
  observability_labels    # label set for metrics and structured log fields
```

The engine owns the event loop plumbing: drain scheduling, buffer fill, slot assignment,
`on_warmup_success` / `on_engine_teardown` callbacks, and backpressure signaling. The
policy object owns what is scraped and how the result is persisted.

---

## Reference implementation

`player_info` is the **reference implementation** for all future workloads. The primitives
it introduced are the canonical building blocks:

| Primitive | Role |
|---|---|
| `BoundedCandidateBuffer` | Bounded async queue between drain and workers. Prevents thundering-herd at claim time. |
| `CandidateProducer` | Drain loop that fills the buffer from the database on a polling cadence. |
| `WarmBrowserPool` | Pre-warmed browser slot pool. Eliminates per-job cold-start latency. |
| `WorkerSlot` | Unit of concurrency. Owns one browser instance and one in-flight job at a time. |
| `RateLimitGate` | Admission gate that enforces inter-request delays and domain-level rate limits. |

When adding a new scraping domain, implement the `WorkloadPolicy` interface and wire it
into the shared engine. Do not copy the buffer or pool logic into the new domain module.

---

## Critical caveat — G-phase scalability does not apply to real FBRef concurrency

The G-phase scalability characterization (5/10/25/50 workers) used **local fake workers**:
asyncpg claim followed by an immediate DONE write, with no real browser and no real HTTP
request. These results characterize claim throughput and queue mechanics only.

They do **not** imply that 25 or 50 concurrent real browser sessions against FBRef are
safe or sustainable. FBRef applies Cloudflare protection, per-IP rate limits, and
Turnstile challenges. The maximum safe real-browser concurrency for FBRef requires a
separate, dedicated validation run with real browsers and real HTTP traffic under
controlled observation.

The current validated ceiling for real FBRef scraping is **workers=2** (from Phase I).
Do not exceed this without dedicated concurrency validation.

---

## Rollout guidance

- Feature flags (`PLAYER_INFO_USE_BUFFER`, `PLAYER_INFO_USE_WARM_POOL`) remain `false` by
  default. Direct mode is the stable production path until the shared engine is promoted.
- Each new workload must be validated against an isolated smoke database (Gate A pattern)
  before enabling any buffering or warm-pool flag in a production environment.
- `player_info` direct mode remains the stable fallback. Any rollback of buffered or
  warm-pool mode requires no code change and no migration — only a flag change and process
  restart.
- `recover_all_stale()` runs unconditionally at startup for all workloads. Any IN_PROGRESS
  or stale rows from a previous interrupted run are reset to PENDING before the first claim.
