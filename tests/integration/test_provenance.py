"""Integration tests for the Provenance ORM model and ProvenanceRepository.

Covers:
- Create with required fields only
- Create with all fields
- Enum rejects invalid values
- get_latest_by_url returns most recent record
- get_latest_by_url returns None for unknown URL
- Append-only: multiple records per URL allowed
- list by run_id

All tests use the async_session fixture (function-scoped, rolled back after each
test). No mocks — real Postgres via testcontainers.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import DataError
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence.models.provenance import Provenance, ProvenanceOutcome
from infrastructure.persistence.repositories.provenance import ProvenanceRepository

# ---------------------------------------------------------------------------
# Task 1 stubs — ORM model tests (RED phase: will fail until model exists)
# ---------------------------------------------------------------------------


class TestProvenanceCreate:
    """Verify that a Provenance row can be inserted with required fields only."""

    async def test_create_required_fields_only(
        self, async_session: AsyncSession
    ) -> None:
        """Insert with url + outcome only; scraped_at is server-populated."""
        row = Provenance(
            url="https://fbref.com/en/squads/",
            outcome=ProvenanceOutcome.SUCCESS,
        )
        async_session.add(row)
        await async_session.flush()
        await async_session.refresh(row)

        assert row.id is not None
        assert row.scraped_at is not None
        assert row.content_hash is None
        assert row.http_status is None
        assert row.error_message is None
        assert row.run_id is None

    async def test_create_all_fields(self, async_session: AsyncSession) -> None:
        """Insert with every column; all values round-trip intact."""
        run_id = uuid.uuid4()
        row = Provenance(
            url="https://fbref.com/en/players/",
            outcome=ProvenanceOutcome.FAILURE,
            content_hash="abc123",
            http_status=500,
            error_message="Internal Server Error",
            run_id=run_id,
        )
        async_session.add(row)
        await async_session.flush()
        await async_session.refresh(row)

        assert row.id is not None
        assert row.url == "https://fbref.com/en/players/"
        assert row.outcome == ProvenanceOutcome.FAILURE
        assert row.content_hash == "abc123"
        assert row.http_status == 500
        assert row.error_message == "Internal Server Error"
        assert row.run_id == run_id

    async def test_enum_rejects_invalid_value(
        self, async_session: AsyncSession
    ) -> None:
        """Inserting an invalid outcome value raises a DB-level error."""
        from sqlalchemy import text

        with pytest.raises(DataError):
            await async_session.execute(
                text(
                    "INSERT INTO sch_infra.provenance (url, outcome) "
                    "VALUES ('https://fbref.com/invalid/', 'INVALID_VALUE')"
                )
            )
            await async_session.flush()


# ---------------------------------------------------------------------------
# Task 3 stubs — Repository tests (RED phase: will fail until repo exists)
# ---------------------------------------------------------------------------


class TestProvenanceRepository:
    """Verify ProvenanceRepository domain queries."""

    async def test_get_latest_by_url_returns_most_recent(
        self, async_session: AsyncSession
    ) -> None:
        """get_latest_by_url returns the record with the latest scraped_at."""
        repo = ProvenanceRepository(async_session)
        url = "https://fbref.com/latest-test/"
        now = datetime.now(tz=UTC)

        old_row = Provenance(
            url=url,
            outcome=ProvenanceOutcome.SUCCESS,
            scraped_at=now - timedelta(hours=2),
        )
        new_row = Provenance(
            url=url,
            outcome=ProvenanceOutcome.FAILURE,
            scraped_at=now - timedelta(hours=1),
        )
        async_session.add(old_row)
        async_session.add(new_row)
        await async_session.flush()

        result = await repo.get_latest_by_url(url)

        assert result is not None
        assert result.outcome == ProvenanceOutcome.FAILURE

    async def test_get_latest_by_url_returns_none_for_unknown_url(
        self, async_session: AsyncSession
    ) -> None:
        """get_latest_by_url returns None when no records exist for the URL."""
        repo = ProvenanceRepository(async_session)

        result = await repo.get_latest_by_url("https://unknown.example.com/")

        assert result is None

    async def test_append_only_multiple_records_same_url(
        self, async_session: AsyncSession
    ) -> None:
        """Two rows for the same URL both persist — no unique constraint violation."""
        url = "https://fbref.com/append-test/"
        row1 = Provenance(url=url, outcome=ProvenanceOutcome.SUCCESS)
        row2 = Provenance(url=url, outcome=ProvenanceOutcome.FAILURE)

        async_session.add(row1)
        await async_session.flush()
        async_session.add(row2)
        await async_session.flush()

        from sqlalchemy import select

        stmt = select(Provenance).where(Provenance.url == url)
        result = await async_session.execute(stmt)
        rows = result.scalars().all()

        assert len(rows) == 2


# ---------------------------------------------------------------------------
# Task 4 — Full integration tests
# ---------------------------------------------------------------------------


class TestProvenanceRepositoryFull:
    """Full integration coverage for ProvenanceRepository."""

    async def test_create_and_get_by_id(self, async_session: AsyncSession) -> None:
        """create() then get() by PK returns the same row."""
        repo = ProvenanceRepository(async_session)
        row = Provenance(
            url="https://fbref.com/crud/",
            outcome=ProvenanceOutcome.SUCCESS,
        )
        created = await repo.create(row)

        fetched = await repo.get(created.id)
        assert fetched is not None
        assert fetched.url == "https://fbref.com/crud/"

    async def test_get_latest_by_url_three_rows_staggered(
        self, async_session: AsyncSession
    ) -> None:
        """With 3 rows at staggered scraped_at, get_latest_by_url returns newest."""
        repo = ProvenanceRepository(async_session)
        url = "https://fbref.com/three-rows/"
        now = datetime.now(tz=UTC)

        rows = [
            Provenance(
                url=url,
                outcome=ProvenanceOutcome.SUCCESS,
                scraped_at=now - timedelta(hours=3),
                http_status=200,
            ),
            Provenance(
                url=url,
                outcome=ProvenanceOutcome.FAILURE,
                scraped_at=now - timedelta(hours=2),
                http_status=503,
            ),
            Provenance(
                url=url,
                outcome=ProvenanceOutcome.SUCCESS,
                scraped_at=now - timedelta(hours=1),
                http_status=200,
                content_hash="newest_hash",
            ),
        ]
        for r in rows:
            async_session.add(r)
        await async_session.flush()

        result = await repo.get_latest_by_url(url)

        assert result is not None
        assert result.content_hash == "newest_hash"
        assert result.http_status == 200

    async def test_list_by_run_id(self, async_session: AsyncSession) -> None:
        """list(run_id=shared_id) returns exactly 2 matching records."""
        repo = ProvenanceRepository(async_session)
        shared_run_id = uuid.uuid4()
        other_run_id = uuid.uuid4()

        rows = [
            Provenance(
                url="https://fbref.com/run/a/",
                outcome=ProvenanceOutcome.SUCCESS,
                run_id=shared_run_id,
            ),
            Provenance(
                url="https://fbref.com/run/b/",
                outcome=ProvenanceOutcome.SUCCESS,
                run_id=shared_run_id,
            ),
            Provenance(
                url="https://fbref.com/run/c/",
                outcome=ProvenanceOutcome.FAILURE,
                run_id=other_run_id,
            ),
        ]
        for r in rows:
            async_session.add(r)
        await async_session.flush()

        results = await repo.list(run_id=shared_run_id)

        assert len(results) == 2
        assert all(r.run_id == shared_run_id for r in results)
