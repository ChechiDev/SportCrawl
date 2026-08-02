"""Bounded candidate dispatch buffer for player_info scraping.

Provides candidate pre-fetch with claim-at-handoff semantics:
1. CandidateProducer peeks PENDING job IDs (no claim) and fills BoundedCandidateBuffer.
2. Workers consume CandidateRef values from the buffer.
3. Durable PostgreSQL claim happens at handoff, inside a short transaction.
4. If claim fails (race), the worker discards the ref and loops.

No DB transaction is held while waiting on buffer capacity (put() blocks
outside any transaction). The buffer contains only lightweight job ID
references — no cookies, browser sessions, HTML payloads, or secrets.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import ClassVar

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CandidateRef:
    """Lightweight reference to a PENDING scrape_queue job.

    Contains only the job ID. No scraped data, cookies, or session state.
    """

    job_id: int


class BoundedCandidateBuffer:
    """Bounded in-memory buffer of unclaimed candidate job references.

    - Producer calls put() outside any DB transaction (may block on backpressure).
    - Workers call get() to receive the next candidate, or None on shutdown.
    - close(n_workers) sends one sentinel per worker so each worker exits cleanly.
    - De-duplication: job_id already in the buffer is silently skipped by put().
    - De-dup entry is removed when the ref is consumed by get(), so a worker that
      dies before claiming allows the producer to re-insert the same ref later.
    """

    # Sleep between capacity checks in the put() backpressure loop.
    _BACKPRESSURE_POLL: ClassVar[float] = 0.05

    def __init__(self, maxsize: int) -> None:
        # Unbounded asyncio.Queue; soft limit enforced in put().
        # Extra capacity ensures close() sentinels always fit.
        self._queue: asyncio.Queue[CandidateRef | None] = asyncio.Queue()
        self._maxsize = maxsize
        self._seen: set[int] = set()
        self._closed = False

    @property
    def empty(self) -> bool:
        return self._queue.empty()

    @property
    def qsize(self) -> int:
        return self._queue.qsize()

    @property
    def is_exhausted(self) -> bool:
        """True when the buffer is closed and all items are consumed."""
        return self._closed and self._queue.empty()

    def abort(self) -> None:
        """Mark the buffer as closed without sending sentinels.

        Used by CandidateProducer.request_stop() to unblock any put() backpressure
        loop that is sleeping. The finally block in CandidateProducer.run() calls
        close(n_workers) to send sentinels afterward.
        """
        self._closed = True

    async def put(self, ref: CandidateRef) -> bool:
        """Put a candidate ref into the buffer.

        Returns True when the candidate is accepted (reserved and enqueued).
        Returns False when the candidate is skipped because the buffer is
        closed or the job_id is already present in _seen.

        Blocks (without holding a DB transaction) when the buffer is at
        capacity. De-dup reservation happens before the backpressure await
        so a concurrent put() with the same job_id sees the reservation
        immediately.
        """
        if self._closed:
            return False
        if ref.job_id in self._seen:
            return False
        # Reserve de-dup slot BEFORE the await point.
        self._seen.add(ref.job_id)
        # Backpressure: block until below soft capacity limit.
        # No DB transaction is held here — callers must close their
        # transaction before calling put().
        while self._queue.qsize() >= self._maxsize and not self._closed:
            await asyncio.sleep(self._BACKPRESSURE_POLL)
        if not self._closed:
            self._queue.put_nowait(ref)
            return True
        # Buffer was closed during the wait; undo reservation so the ref
        # can be re-inserted if the buffer is reused after a restart.
        self._seen.discard(ref.job_id)
        return False

    async def get(self) -> CandidateRef | None:
        """Wait for the next candidate ref, or None on shutdown."""
        ref = await self._queue.get()
        if ref is not None:
            # Remove from seen so the producer can re-insert if the worker
            # dies before claiming.
            self._seen.discard(ref.job_id)
        return ref

    def task_done(self) -> None:
        self._queue.task_done()

    def close(self, n_workers: int) -> None:
        """Signal shutdown to n_workers workers by sending one sentinel each."""
        self._closed = True
        for _ in range(n_workers):
            self._queue.put_nowait(None)


class CandidateProducer:
    """Async producer that fills a BoundedCandidateBuffer with PENDING job IDs.

    Calls peek_fn() to read unclaimed PENDING candidate IDs (no claim, no lock).
    The transaction inside peek_fn must be closed before put() is called so
    no DB transaction is held while waiting on buffer capacity.

    Only one producer may be active per process. Raises RuntimeError if a
    second instance is created while the first is still running.

    Args:
        peek_fn: Async callable returning a list of PENDING job IDs (no claim).
        buffer:  The BoundedCandidateBuffer to fill.
        n_workers: Number of workers; used to send the right number of sentinels.
        poll_interval: Seconds to sleep when no new candidates are found.
        step2_done: Optional event; producer waits for it before stopping on
                    empty queue (mirrors direct-claim step2_done semantics).
    """

    _active: ClassVar[bool] = False

    def __init__(
        self,
        peek_fn: Callable[[], Awaitable[list[int]]],
        buffer: BoundedCandidateBuffer,
        n_workers: int,
        poll_interval: float = 5.0,
        step2_done: asyncio.Event | None = None,
        wait_fn: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        if CandidateProducer._active:
            raise RuntimeError(
                "CandidateProducer: only one producer may be active per process"
            )
        CandidateProducer._active = True
        self._peek_fn = peek_fn
        self._buffer = buffer
        self._n_workers = n_workers
        self._poll_interval = poll_interval
        self._step2_done = step2_done
        self._wait_fn = wait_fn
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        """Request the producer to stop after its current iteration.

        Calls buffer.abort() so any in-progress put() backpressure loop
        unblocks immediately rather than waiting for the next capacity poll.
        """
        self._stop.set()
        self._buffer.abort()

    async def run(self) -> None:
        """Run the producer loop until the queue is exhausted or stop is requested."""
        try:
            while not self._stop.is_set():
                if self._wait_fn is not None:
                    await self._wait_fn()
                ids = await self._peek_fn()
                # Transaction inside peek_fn is closed before put() is called.
                if ids:
                    accepted = 0
                    for job_id in ids:
                        if self._stop.is_set():
                            break
                        if await self._buffer.put(CandidateRef(job_id=job_id)):
                            accepted += 1
                    _log.debug(
                        "dispatch buffer: enqueued %d/%d candidates",
                        accepted,
                        len(ids),
                    )
                    if accepted == 0 and not self._stop.is_set():
                        # Every ID in the batch was already buffered (duplicate-
                        # only peek). Back off so we do not hot-poll PostgreSQL
                        # when the dedup set is saturated.
                        await asyncio.sleep(self._poll_interval)
                else:
                    # Queue appears empty. Stop if step2 is also done (or absent).
                    step2_ready = (
                        self._step2_done is None or self._step2_done.is_set()
                    )
                    if step2_ready and self._buffer.empty:
                        _log.info("dispatch buffer: queue exhausted, shutting down")
                        break
                    await asyncio.sleep(self._poll_interval)
        finally:
            CandidateProducer._active = False
            self._buffer.close(self._n_workers)
            _log.debug("dispatch buffer: closed with %d sentinels", self._n_workers)


def build_dispatch_buffer_if_enabled(
    enabled: bool,
    buffer_size: int,
) -> BoundedCandidateBuffer | None:
    """Create a BoundedCandidateBuffer only when the feature flag is enabled."""
    if not enabled:
        return None
    return BoundedCandidateBuffer(maxsize=buffer_size)
