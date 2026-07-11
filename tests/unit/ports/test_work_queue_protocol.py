"""Unit tests for the WorkQueuePort protocol contract (REQ-9.5).

Verifies that:
- A concrete fake implementing WorkQueuePort satisfies isinstance() check.
- A fake that is missing a required method is NOT an instance.
- JobRecordProtocol is satisfied by a plain dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ports.work_queue import JobRecordProtocol, WorkQueuePort


# ---------------------------------------------------------------------------
# Minimal fake adapter that satisfies the full protocol contract
# ---------------------------------------------------------------------------


class _FakeAdapter:
    """In-memory implementation of WorkQueuePort used in tests."""

    async def enqueue(self, url: str) -> JobRecordProtocol:
        return _FakeJobRecord(id=1, url=url, status="PENDING")

    async def get_job(self, job_id: int) -> JobRecordProtocol | None:
        return None


@dataclass
class _FakeJobRecord:
    id: int
    url: str
    status: str


# ---------------------------------------------------------------------------
# Incomplete fake — missing get_job
# ---------------------------------------------------------------------------


class _IncompleteAdapter:
    async def enqueue(self, url: str) -> JobRecordProtocol:
        return _FakeJobRecord(id=1, url=url, status="PENDING")

    # get_job intentionally omitted


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWorkQueuePortProtocol:
    """Structural protocol checks — no network or DB required."""

    def test_fake_adapter_is_instance_of_work_queue_port(self) -> None:
        """A complete fake satisfies isinstance(WorkQueuePort) — REQ-9.5."""
        adapter = _FakeAdapter()
        assert isinstance(adapter, WorkQueuePort)

    def test_incomplete_adapter_is_not_instance_of_work_queue_port(self) -> None:
        """A fake missing get_job does NOT satisfy the protocol."""
        adapter = _IncompleteAdapter()
        assert not isinstance(adapter, WorkQueuePort)

    def test_job_record_protocol_satisfied_by_dataclass(self) -> None:
        """A plain dataclass with id/url/status satisfies JobRecordProtocol."""
        record = _FakeJobRecord(id=42, url="https://fbref.com/", status="PENDING")
        assert isinstance(record, JobRecordProtocol)

    def test_work_queue_port_has_enqueue_method(self) -> None:
        """WorkQueuePort declares an enqueue method."""
        assert hasattr(WorkQueuePort, "enqueue")

    def test_work_queue_port_has_get_job_method(self) -> None:
        """WorkQueuePort declares a get_job method."""
        assert hasattr(WorkQueuePort, "get_job")
