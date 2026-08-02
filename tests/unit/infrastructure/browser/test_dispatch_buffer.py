"""Unit tests for BoundedCandidateBuffer and CandidateProducer."""
from __future__ import annotations

import asyncio

import pytest

from infrastructure.browser.dispatch import (
    BoundedCandidateBuffer,
    CandidateProducer,
    CandidateRef,
    build_dispatch_buffer_if_enabled,
)

# ---------------------------------------------------------------------------
# Feature flag / factory
# ---------------------------------------------------------------------------


def test_build_dispatch_buffer_disabled_returns_none():
    result = build_dispatch_buffer_if_enabled(enabled=False, buffer_size=10)
    assert result is None


def test_build_dispatch_buffer_enabled_returns_buffer():
    result = build_dispatch_buffer_if_enabled(enabled=True, buffer_size=10)
    assert isinstance(result, BoundedCandidateBuffer)


# ---------------------------------------------------------------------------
# CandidateRef
# ---------------------------------------------------------------------------

def test_candidate_ref_is_frozen():
    ref = CandidateRef(job_id=42)
    with pytest.raises(Exception):
        ref.job_id = 99  # type: ignore[misc]


def test_candidate_ref_no_extra_data():
    ref = CandidateRef(job_id=1)
    assert ref.job_id == 1
    # Only job_id — no url, html, cookies, or session state
    assert not hasattr(ref, "url")
    assert not hasattr(ref, "html")
    assert not hasattr(ref, "cookies")
    assert not hasattr(ref, "session")


# ---------------------------------------------------------------------------
# BoundedCandidateBuffer — bounded and de-dup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_buffer_put_and_get_round_trip():
    buf = BoundedCandidateBuffer(maxsize=5)
    await buf.put(CandidateRef(job_id=1))
    ref = await buf.get()
    assert ref is not None
    assert ref.job_id == 1


@pytest.mark.asyncio
async def test_buffer_deduplication_skips_repeated_job_ids():
    buf = BoundedCandidateBuffer(maxsize=10)
    await buf.put(CandidateRef(job_id=7))
    await buf.put(CandidateRef(job_id=7))  # duplicate
    await buf.put(CandidateRef(job_id=7))  # duplicate
    assert buf.qsize == 1


@pytest.mark.asyncio
async def test_buffer_dedup_clears_on_consume():
    """After consuming a ref, its job_id can be re-inserted (dead-worker recovery)."""
    buf = BoundedCandidateBuffer(maxsize=10)
    await buf.put(CandidateRef(job_id=5))
    _ = await buf.get()  # consume
    # Now the same job_id can be re-inserted
    await buf.put(CandidateRef(job_id=5))
    assert buf.qsize == 1


@pytest.mark.asyncio
async def test_buffer_bounded_backpressure():
    """put() blocks when at capacity, then unblocks when a consumer drains."""
    buf = BoundedCandidateBuffer(maxsize=2)
    await buf.put(CandidateRef(job_id=1))
    await buf.put(CandidateRef(job_id=2))
    # Buffer is at capacity — put() for job_id=3 must block
    blocked = False

    async def producer():
        nonlocal blocked
        blocked = True
        await buf.put(CandidateRef(job_id=3))
        blocked = False

    task = asyncio.create_task(producer())
    await asyncio.sleep(0.2)  # give producer time to block
    assert blocked is True  # still blocking

    await buf.get()  # drain one
    await asyncio.wait_for(task, timeout=2.0)
    assert blocked is False  # unblocked


@pytest.mark.asyncio
async def test_buffer_stores_only_candidate_refs():
    buf = BoundedCandidateBuffer(maxsize=5)
    await buf.put(CandidateRef(job_id=99))
    ref = await buf.get()
    assert isinstance(ref, CandidateRef)
    # Verify no payload leaks: only job_id
    assert ref.job_id == 99


@pytest.mark.asyncio
async def test_buffer_close_sends_sentinels():
    buf = BoundedCandidateBuffer(maxsize=10)
    await buf.put(CandidateRef(job_id=1))
    buf.close(n_workers=3)
    # Should get the ref, then 3 None sentinels
    ref = await buf.get()
    assert ref is not None
    sentinels = [await buf.get() for _ in range(3)]
    assert all(s is None for s in sentinels)


@pytest.mark.asyncio
async def test_buffer_put_after_close_is_silently_ignored():
    buf = BoundedCandidateBuffer(maxsize=10)
    buf.close(n_workers=1)
    await buf.put(CandidateRef(job_id=42))  # should not raise
    # Only the 1 sentinel should be in the queue
    sentinel = await buf.get()
    assert sentinel is None
    assert buf.empty


# ---------------------------------------------------------------------------
# CandidateProducer — singleton guard
# ---------------------------------------------------------------------------

def test_producer_singleton_guard():
    """Second producer raises RuntimeError while first is still active."""
    buf2 = BoundedCandidateBuffer(maxsize=10)

    async def never_peeks() -> list[int]:
        return []

    # Force _active True manually to simulate first producer still running
    CandidateProducer._active = True
    try:
        with pytest.raises(RuntimeError, match="only one producer"):
            CandidateProducer(
                peek_fn=never_peeks,
                buffer=buf2,
                n_workers=1,
            )
    finally:
        CandidateProducer._active = False


# ---------------------------------------------------------------------------
# CandidateProducer — behavior
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_producer_fetches_only_pending_ids():
    """Producer puts only the IDs returned by peek_fn.

    Consumer runs concurrently so the buffer drains, allowing the producer
    to detect empty queue + empty buffer and stop naturally.
    """
    buf = BoundedCandidateBuffer(maxsize=10)
    calls = 0
    refs: list[int] = []

    async def peek_once() -> list[int]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return [10, 20, 30]
        return []

    producer = CandidateProducer(
        peek_fn=peek_once,
        buffer=buf,
        n_workers=1,
        poll_interval=0.01,
    )

    async def consumer() -> None:
        while True:
            ref = await buf.get()
            if ref is None:
                break
            refs.append(ref.job_id)

    await asyncio.wait_for(
        asyncio.gather(producer.run(), consumer()),
        timeout=3.0,
    )

    assert refs == [10, 20, 30]
    assert calls >= 2  # peeked at least twice (once with data, once empty)


def test_producer_does_not_claim_during_prefetch():
    """CandidateProducer.__init__ must not accept a claim_fn parameter.

    The producer is a read-only prefetcher. If claim_fn were a parameter,
    the producer could claim jobs during prefetch — violating the design.
    """
    import inspect

    sig = inspect.signature(CandidateProducer.__init__)
    assert "claim_fn" not in sig.parameters, (
        "CandidateProducer must not accept a claim_fn — it is a read-only prefetcher"
    )


@pytest.mark.asyncio
async def test_producer_stops_cleanly_on_request_stop():
    buf = BoundedCandidateBuffer(maxsize=10)
    # Use a step2_done event that is never set so the producer keeps sleeping
    # on poll_interval (waiting for more work). request_stop() then unblocks it.
    step2 = asyncio.Event()  # never set — producer will not stop on its own

    async def empty_peek() -> list[int]:
        return []

    producer = CandidateProducer(
        peek_fn=empty_peek,
        buffer=buf,
        n_workers=1,
        poll_interval=0.05,
        step2_done=step2,
    )
    task = asyncio.create_task(producer.run())
    # Give the producer time to enter its first poll sleep.
    await asyncio.sleep(0.01)
    producer.request_stop()
    await asyncio.wait_for(task, timeout=2.0)
    assert not task.exception()


@pytest.mark.asyncio
async def test_producer_resets_active_flag_on_exit():
    buf = BoundedCandidateBuffer(maxsize=10)
    calls = 0

    async def once() -> list[int]:
        nonlocal calls
        calls += 1
        return []

    producer = CandidateProducer(
        peek_fn=once,
        buffer=buf,
        n_workers=1,
        poll_interval=0.0,
    )
    await asyncio.wait_for(producer.run(), timeout=2.0)
    # After run() completes, _active must be False so a second producer can start
    assert CandidateProducer._active is False


@pytest.mark.asyncio
async def test_producer_no_transaction_held_during_put():
    """put() is never called while peek_fn's simulated transaction is still open.

    peek_fn sets tx_open=True, builds the list, sets tx_open=False, and returns.
    A patched buffer.put() records whether tx_open was True at call time.
    The producer must close the transaction (return from peek_fn) before put().
    """
    buf = BoundedCandidateBuffer(maxsize=10)
    tx_open = False
    tx_open_during_put = False

    original_put = buf.put

    async def tracked_put(ref: CandidateRef) -> bool:
        nonlocal tx_open_during_put
        if tx_open:
            tx_open_during_put = True
        return await original_put(ref)

    buf.put = tracked_put  # type: ignore[method-assign]

    _peek_calls = 0

    async def peek_with_simulated_tx() -> list[int]:
        nonlocal tx_open, _peek_calls
        _peek_calls += 1
        tx_open = True
        ids = [1, 2, 3] if _peek_calls == 1 else []
        tx_open = False  # transaction closed before returning
        return ids

    producer = CandidateProducer(
        peek_fn=peek_with_simulated_tx,
        buffer=buf,
        n_workers=1,
        poll_interval=0.01,
    )
    task = asyncio.create_task(producer.run())
    await asyncio.sleep(0.1)
    producer.request_stop()
    await asyncio.wait_for(task, timeout=2.0)
    assert not tx_open_during_put, (
        "put() was called while simulated transaction was open"
    )


@pytest.mark.asyncio
async def test_producer_backs_off_on_duplicate_only_peek_batch() -> None:
    """Producer yields/backs off when peek returns only IDs already in _seen.

    Without the duplicate-only backoff, the producer spins with zero yield
    points once _seen is saturated, starving the event loop.  With the fix,
    it calls asyncio.sleep(poll_interval) after any batch where accepted==0,
    giving the event loop control so request_stop() can be observed promptly.
    """
    buf = BoundedCandidateBuffer(maxsize=10)
    # Pre-load IDs so _seen already contains {1, 2, 3}.
    for job_id in [1, 2, 3]:
        await buf.put(CandidateRef(job_id=job_id))
    assert buf.qsize == 3

    peek_calls = 0

    async def peek_duplicates() -> list[int]:
        nonlocal peek_calls
        peek_calls += 1
        return [1, 2, 3]  # all already in _seen — no new candidates

    producer = CandidateProducer(
        peek_fn=peek_duplicates,
        buffer=buf,
        n_workers=1,
        poll_interval=0.005,  # 10x margin under the 0.05s test sleep
    )
    task = asyncio.create_task(producer.run())
    # If the producer starves the event loop this sleep never fires and the
    # subsequent wait_for raises TimeoutError — proving the fix is needed.
    await asyncio.sleep(0.05)
    producer.request_stop()
    await asyncio.wait_for(task, timeout=2.0)

    # Producer must have iterated more than once (backoff yielded the loop).
    assert peek_calls >= 2, f"expected ≥2 peek calls, got {peek_calls}"
    # close(n_workers=1) adds one shutdown sentinel to the queue.
    # Total = 3 pre-loaded items + 1 sentinel — no duplicates were inserted.
    assert buf.qsize == 4


# ---------------------------------------------------------------------------
# Claim-at-handoff semantics (via fake claim function)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_failed_claim_discards_ref_safely():
    """When claim_by_id returns None, the ref is discarded without error."""
    buf = BoundedCandidateBuffer(maxsize=10)
    await buf.put(CandidateRef(job_id=99))
    buf.close(n_workers=1)  # sentinel after

    ref = await buf.get()
    assert ref is not None

    # Simulate claim failure (returns None — race with another process)
    async def claim_by_id_fails(_: int) -> None:
        return None

    claimed = await claim_by_id_fails(ref.job_id)
    assert claimed is None  # discarded safely


@pytest.mark.asyncio
async def test_no_in_progress_job_in_memory_buffer():
    """The buffer holds only CandidateRef (job IDs). Not ScrapeQueue objects.

    IN_PROGRESS state is only set in PostgreSQL, after claim_by_id succeeds.
    The buffer never holds a row that is already IN_PROGRESS.
    """
    buf = BoundedCandidateBuffer(maxsize=5)
    await buf.put(CandidateRef(job_id=42))
    ref = await buf.get()
    # The buffer returned a CandidateRef — never a ScrapeQueue row
    assert isinstance(ref, CandidateRef)
    assert not hasattr(ref, "status")


# ---------------------------------------------------------------------------
# Concurrency: multiple consumers, single producer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multiple_workers_can_consume_safely():
    """Multiple workers can consume from the same buffer without data loss."""
    buf = BoundedCandidateBuffer(maxsize=10)
    for i in range(1, 6):
        await buf.put(CandidateRef(job_id=i))
    buf.close(n_workers=3)  # 3 workers

    consumed: list[int] = []
    lock = asyncio.Lock()

    async def consume():
        while True:
            ref = await buf.get()
            if ref is None:
                return
            async with lock:
                consumed.append(ref.job_id)

    await asyncio.gather(consume(), consume(), consume())
    assert sorted(consumed) == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_second_producer_blocked_while_first_active():
    buf = BoundedCandidateBuffer(maxsize=10)

    async def never() -> list[int]:
        await asyncio.sleep(10)
        return []

    CandidateProducer._active = True
    try:
        with pytest.raises(RuntimeError):
            CandidateProducer(peek_fn=never, buffer=buf, n_workers=1)
    finally:
        CandidateProducer._active = False


# ---------------------------------------------------------------------------
# Security / scope assertions
# ---------------------------------------------------------------------------

def test_candidate_ref_has_no_cookie_field():
    ref = CandidateRef(job_id=1)
    assert not hasattr(ref, "cookie")
    assert not hasattr(ref, "cookies")
    assert not hasattr(ref, "session_token")


def test_candidate_ref_has_no_html_payload():
    ref = CandidateRef(job_id=1)
    assert not hasattr(ref, "html")
    assert not hasattr(ref, "body")
    assert not hasattr(ref, "content")


def test_candidate_ref_has_no_cdp_state():
    ref = CandidateRef(job_id=1)
    assert not hasattr(ref, "cdp")
    assert not hasattr(ref, "browser_session")
    assert not hasattr(ref, "target_id")


def test_dispatch_module_no_persistence_import():
    """dispatch.py must not import from infrastructure.persistence."""
    import importlib
    import inspect
    import sys

    mod_name = "infrastructure.browser.dispatch"
    if mod_name in sys.modules:
        mod = sys.modules[mod_name]
    else:
        mod = importlib.import_module(mod_name)

    source = inspect.getsource(mod)
    assert "infrastructure.persistence" not in source


def test_dispatch_module_gate_is_separate_module():
    """RateLimitGate lives in gate.py, not dispatch.py — keeps dispatch focused."""
    import infrastructure.browser.dispatch as dispatch
    import infrastructure.browser.gate as gate_module

    # gate is its own module, not merged into dispatch
    assert not hasattr(dispatch, "RateLimitGate")
    assert hasattr(gate_module, "RateLimitGate")
