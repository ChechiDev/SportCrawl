"""Integration tests for _startup_drain against a real PostgreSQL database."""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from infrastructure.persistence.repositories.player_info_queue import (
    PlayerInfoConsistencyError,
    record_job_failure,
)
from scripts.scrape_player_info import _startup_drain


@pytest_asyncio.fixture(loop_scope="function")
async def session_factory(_integration_db_url: URL):
    engine = create_async_engine(_integration_db_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _insert_player(session, player_id: str) -> None:
    """Insert a minimal tbl_players row to satisfy the FK on tbl_player_urls."""
    await session.execute(
        text(
            "INSERT INTO sch_fbref_shared.tbl_players"
            " (player_id, full_name, career_start, career_end)"
            " VALUES (:pid, :name, 2015, 2024) ON CONFLICT DO NOTHING"
        ),
        {"pid": player_id, "name": player_id},
    )
    await session.flush()


async def _insert_player_url(
    session,
    *,
    fk_player: str,
    url: str,
    status: str = "PENDING",
    priority: int = 5,
) -> int:
    result = await session.execute(
        text(
            "INSERT INTO sch_fbref_backend.tbl_player_urls"
            " (fk_player, url_type, url, status, next_scrape_at, priority)"
            " VALUES (:fk_player, 'profile', :url, :status,"
            "         now() - interval '1 hour', :priority)"
            " RETURNING id"
        ),
        {
            "fk_player": fk_player,
            "url": url,
            "status": status,
            "priority": priority,
        },
    )
    row = result.one()
    await session.flush()
    return row[0]


async def _insert_queue_row(
    session, *, url: str, status: str, fk_url_registry_id=None
) -> int:
    result = await session.execute(
        text(
            "INSERT INTO sch_fbref_infra.scrape_queue"
            " (url, domain, status, job_type, fk_url_registry_id)"
            " VALUES (:url, 'fbref.com', :status, 'player_info', :fk)"
            " RETURNING id"
        ),
        {"url": url, "status": status, "fk": fk_url_registry_id},
    )
    row = result.one()
    await session.flush()
    return row[0]


async def _count_queue_rows(sf, *, url=None, status=None) -> int:
    async with sf() as s:
        q = (
            "SELECT COUNT(*) FROM sch_fbref_infra.scrape_queue"
            " WHERE job_type = 'player_info'"
        )
        params: dict = {}
        if url is not None:
            q += " AND url = :url"
            params["url"] = url
        if status is not None:
            q += " AND status = :status"
            params["status"] = status
        result = await s.execute(text(q), params)
        return result.scalar_one()


async def test_no_due_url_no_insert(session_factory):
    # No player_url rows due → drain returns 0
    count = await _startup_drain(session_factory, batch_size=100)
    assert count == 0
    total = await _count_queue_rows(session_factory)
    assert total == 0


async def test_pending_url_inserts_queue_row(session_factory):
    player_id = "t_pend1"
    url = f"https://fbref.com/en/players/{player_id}/player"
    async with session_factory() as s:
        await _insert_player(s, player_id)
        await _insert_player_url(s, fk_player=player_id, url=url)
        await s.commit()

    count = await _startup_drain(session_factory, batch_size=100)
    assert count == 1

    total = await _count_queue_rows(session_factory, url=url, status="PENDING")
    assert total == 1


async def test_existing_pending_queue_not_reactivated(session_factory):
    player_id = "t_xpend2"
    url = f"https://fbref.com/en/players/{player_id}/player"
    async with session_factory() as s:
        await _insert_player(s, player_id)
        url_id = await _insert_player_url(s, fk_player=player_id, url=url)
        await _insert_queue_row(
            s, url=url, status="PENDING", fk_url_registry_id=url_id
        )
        await s.commit()

    count = await _startup_drain(session_factory, batch_size=100)
    assert count == 0

    total = await _count_queue_rows(session_factory, url=url, status="PENDING")
    assert total == 1


async def test_existing_in_progress_not_modified(session_factory):
    player_id = "t_inprog3"
    url = f"https://fbref.com/en/players/{player_id}/player"
    async with session_factory() as s:
        await _insert_player(s, player_id)
        url_id = await _insert_player_url(s, fk_player=player_id, url=url)
        await _insert_queue_row(
            s, url=url, status="IN_PROGRESS", fk_url_registry_id=url_id
        )
        await s.commit()

    count = await _startup_drain(session_factory, batch_size=100)
    assert count == 0

    total = await _count_queue_rows(
        session_factory, url=url, status="IN_PROGRESS"
    )
    assert total == 1


async def test_existing_done_reactivated_exactly_once(session_factory):
    player_id = "t_done4"
    url = f"https://fbref.com/en/players/{player_id}/player"
    async with session_factory() as s:
        await _insert_player(s, player_id)
        url_id = await _insert_player_url(s, fk_player=player_id, url=url)
        await _insert_queue_row(
            s, url=url, status="DONE", fk_url_registry_id=url_id
        )
        await s.commit()

    count = await _startup_drain(session_factory, batch_size=100)
    assert count == 1
    # second call should not reactivate again
    count2 = await _startup_drain(session_factory, batch_size=100)
    assert count2 == 0


async def test_existing_failed_not_modified(session_factory):
    player_id = "t_fail5"
    url = f"https://fbref.com/en/players/{player_id}/player"
    async with session_factory() as s:
        await _insert_player(s, player_id)
        url_id = await _insert_player_url(s, fk_player=player_id, url=url)
        await _insert_queue_row(
            s, url=url, status="FAILED", fk_url_registry_id=url_id
        )
        await s.commit()

    count = await _startup_drain(session_factory, batch_size=100)
    assert count == 0

    total = await _count_queue_rows(session_factory, url=url, status="FAILED")
    assert total == 1


async def test_batch_size_limits_rows_per_call(session_factory):
    base = "t_batch6"
    async with session_factory() as s:
        for i in range(5):
            pid = f"{base}_{i}"
            url = f"https://fbref.com/en/players/{pid}/player"
            await _insert_player(s, pid)
            await _insert_player_url(s, fk_player=pid, url=url)
        await s.commit()

    # _startup_drain loops until exhausted; batch_size=2 issues 3 SQL passes (2+2+1).
    # The function returns the cumulative total across all passes.
    total = await _startup_drain(session_factory, batch_size=2)
    assert total == 5

    # Second call finds no eligible rows.
    total2 = await _startup_drain(session_factory, batch_size=2)
    assert total2 == 0


async def test_large_drain_terminates(session_factory):
    base = "t_large7"
    async with session_factory() as s:
        for i in range(25):
            pid = f"{base}_{i:02d}"
            url = f"https://fbref.com/en/players/{pid}/player"
            await _insert_player(s, pid)
            await _insert_player_url(s, fk_player=pid, url=url)
        await s.commit()

    total = 0
    for _ in range(10):  # safety cap
        n = await _startup_drain(session_factory, batch_size=10)
        total += n
        if n == 0:
            break
    assert total == 25


async def test_ordering_by_priority(session_factory):
    base = "t_prio8"
    urls = []
    async with session_factory() as s:
        for i, priority in enumerate([10, 1, 5]):
            pid = f"{base}_{i}"
            url = f"https://fbref.com/en/players/{pid}/player"
            await _insert_player(s, pid)
            await _insert_player_url(s, fk_player=pid, url=url, priority=priority)
            urls.append((priority, url))
        await s.commit()

    # batch_size=1 forces each SQL pass to insert exactly one row.
    # The ORDER BY bpu.priority ASC ensures the lowest-numbered priority
    # (highest importance) is selected first across passes.
    c = await _startup_drain(session_factory, batch_size=1)
    assert c == 3  # all 3 rows drained across 3 single-row passes

    # The row with priority=1 must be in the queue (ordering was respected).
    async with session_factory() as s:
        result = await s.execute(
            text(
                "SELECT sq.url FROM sch_fbref_infra.scrape_queue sq"
                " JOIN sch_fbref_backend.tbl_player_urls bpu"
                "   ON sq.fk_url_registry_id = bpu.id"
                " WHERE sq.job_type = 'player_info' AND sq.status = 'PENDING'"
                " ORDER BY bpu.priority ASC LIMIT 1"
            )
        )
        row = result.one_or_none()
        assert row is not None
        assert "t_prio8_1" in row[0]  # the pid with priority=1


async def test_concurrent_drains_no_duplicates(session_factory):
    base = "t_conc9"
    async with session_factory() as s:
        for i in range(5):
            pid = f"{base}_{i}"
            url = f"https://fbref.com/en/players/{pid}/player"
            await _insert_player(s, pid)
            await _insert_player_url(s, fk_player=pid, url=url)
        await s.commit()

    # asyncio.gather interleaves both drains in one event loop. PostgreSQL
    # serializes concurrent inserts via row-level locking on
    # uq_scrape_queue_url_job_type.
    # The second drain's INSERT hits ON CONFLICT WHERE status='DONE' — rows are
    # PENDING (not DONE), so DO UPDATE condition is false → DO NOTHING →
    # RETURNING 0. Result is always 5+0=5, not 5+5=10. This is deterministic.
    results = await asyncio.gather(
        _startup_drain(session_factory, batch_size=5),
        _startup_drain(session_factory, batch_size=5),
    )
    total = sum(results)
    assert total == 5  # no duplicates


async def test_legacy_null_fk_does_not_block_due_url(session_factory):
    # url_A has a queue row with NULL fk — legacy row
    url_a = "https://fbref.com/en/players/t_lfk_a/player"
    async with session_factory() as s:
        await _insert_queue_row(
            s, url=url_a, status="PENDING", fk_url_registry_id=None
        )

        # url_B is a new due player_url row
        pid_b = "t_lfk_b"
        url_b = f"https://fbref.com/en/players/{pid_b}/player"
        await _insert_player(s, pid_b)
        await _insert_player_url(s, fk_player=pid_b, url=url_b)
        await s.commit()

    count = await _startup_drain(session_factory, batch_size=100)
    assert count == 1  # only url_B inserted

    total_b = await _count_queue_rows(session_factory, url=url_b, status="PENDING")
    assert total_b == 1

    # url_A's NULL FK row is untouched
    total_a = await _count_queue_rows(session_factory, url=url_a)
    assert total_a == 1


async def test_retryable_transition(session_factory):
    player_id = "t_retry10"
    url = f"https://fbref.com/en/players/{player_id}/player"
    async with session_factory() as s:
        await _insert_player(s, player_id)
        url_id = await _insert_player_url(s, fk_player=player_id, url=url)
        queue_id = await _insert_queue_row(
            s, url=url, status="IN_PROGRESS", fk_url_registry_id=url_id
        )
        # set retry_count=0 explicitly
        await s.execute(
            text(
                "UPDATE sch_fbref_infra.scrape_queue"
                " SET retry_count=0, locked_at=now() WHERE id=:id"
            ),
            {"id": queue_id},
        )
        await s.commit()

    await record_job_failure(
        queue_id, "test error", max_retries=5, session_factory=session_factory
    )

    async with session_factory() as s:
        result = await s.execute(
            text(
                "SELECT status, retry_count"
                " FROM sch_fbref_infra.scrape_queue WHERE id=:id"
            ),
            {"id": queue_id},
        )
        row = result.one()
        assert row[0] == "PENDING"
        assert row[1] == 1

        result2 = await s.execute(
            text(
                "SELECT retry_count"
                " FROM sch_fbref_backend.tbl_player_urls WHERE id=:id"
            ),
            {"id": url_id},
        )
        url_row = result2.one()
        assert url_row[0] == 1


async def test_terminal_transition(session_factory):
    player_id = "t_term11"
    url = f"https://fbref.com/en/players/{player_id}/player"
    async with session_factory() as s:
        await _insert_player(s, player_id)
        url_id = await _insert_player_url(s, fk_player=player_id, url=url)
        queue_id = await _insert_queue_row(
            s, url=url, status="IN_PROGRESS", fk_url_registry_id=url_id
        )
        # set retry_count=4 so next failure (5) hits ceiling=5
        await s.execute(
            text(
                "UPDATE sch_fbref_infra.scrape_queue"
                " SET retry_count=4, locked_at=now() WHERE id=:id"
            ),
            {"id": queue_id},
        )
        await s.commit()

    await record_job_failure(
        queue_id, "fatal error", max_retries=5, session_factory=session_factory
    )

    async with session_factory() as s:
        result = await s.execute(
            text(
                "SELECT status, retry_count"
                " FROM sch_fbref_infra.scrape_queue WHERE id=:id"
            ),
            {"id": queue_id},
        )
        row = result.one()
        assert row[0] == "FAILED"
        assert row[1] == 5

        result2 = await s.execute(
            text(
                "SELECT status FROM sch_fbref_backend.tbl_player_urls WHERE id=:id"
            ),
            {"id": url_id},
        )
        url_row = result2.one()
        assert url_row[0] == "STALE"


async def test_url_row_missing_raises_consistency_error(session_factory):
    """record_job_failure raises PlayerInfoConsistencyError when FK non-null
    but URL row does not exist. Queue row must remain unchanged."""
    url = "https://fbref.com/en/players/t_cons1/player"
    async with session_factory() as s:
        await s.execute(
            text(
                "INSERT INTO sch_fbref_infra.scrape_queue"
                " (url, domain, status, job_type, fk_url_registry_id,"
                "  retry_count, locked_at)"
                " VALUES (:url, 'fbref.com', 'IN_PROGRESS', 'player_info',"
                "  999999, 0, now())"
            ),
            {"url": url},
        )
        await s.commit()

    async with session_factory() as s:
        result = await s.execute(
            text(
                "SELECT id, retry_count, status FROM sch_fbref_infra.scrape_queue"
                " WHERE url = :url AND job_type = 'player_info'"
            ),
            {"url": url},
        )
        queue_row = result.one()
        queue_id = queue_row.id
        original_status = queue_row.status
        original_retry = queue_row.retry_count

    with pytest.raises(PlayerInfoConsistencyError):
        await record_job_failure(
            queue_id,
            "test error",
            max_retries=5,
            session_factory=session_factory,
        )

    async with session_factory() as s:
        result2 = await s.execute(
            text(
                "SELECT status, retry_count FROM sch_fbref_infra.scrape_queue"
                " WHERE id = :id"
            ),
            {"id": queue_id},
        )
        row = result2.one()
        assert row.status == original_status
        assert row.retry_count == original_retry


async def test_retry_counters_reconciled_retryable(session_factory):
    """Both retry_count fields equal new_retry after a retryable transition."""
    player_id = "t_cnt_r1"
    url = f"https://fbref.com/en/players/{player_id}/player"
    async with session_factory() as s:
        await _insert_player(s, player_id)
        url_id = await _insert_player_url(s, fk_player=player_id, url=url)
        queue_id = await _insert_queue_row(
            s,
            url=url,
            status="IN_PROGRESS",
            fk_url_registry_id=url_id,
        )
        # Set both counters to the same starting value
        await s.execute(
            text(
                "UPDATE sch_fbref_infra.scrape_queue"
                " SET retry_count=2, locked_at=now() WHERE id=:id"
            ),
            {"id": queue_id},
        )
        await s.execute(
            text(
                "UPDATE sch_fbref_backend.tbl_player_urls"
                " SET retry_count=2 WHERE id=:id"
            ),
            {"id": url_id},
        )
        await s.commit()

    await record_job_failure(
        queue_id, "err", max_retries=5, session_factory=session_factory,
    )

    async with session_factory() as s:
        qr = (
            await s.execute(
                text(
                    "SELECT status, retry_count"
                    " FROM sch_fbref_infra.scrape_queue WHERE id=:id"
                ),
                {"id": queue_id},
            )
        ).one()
        ur = (
            await s.execute(
                text(
                    "SELECT retry_count"
                    " FROM sch_fbref_backend.tbl_player_urls WHERE id=:id"
                ),
                {"id": url_id},
            )
        ).one()
        assert qr.status == "PENDING"
        assert qr.retry_count == 3
        assert ur.retry_count == 3  # must match queue, not independently incremented


async def test_retry_counters_reconciled_terminal(session_factory):
    """Both retry_count fields equal new_retry after a terminal transition."""
    player_id = "t_cnt_t1"
    url = f"https://fbref.com/en/players/{player_id}/player"
    async with session_factory() as s:
        await _insert_player(s, player_id)
        url_id = await _insert_player_url(s, fk_player=player_id, url=url)
        queue_id = await _insert_queue_row(
            s,
            url=url,
            status="IN_PROGRESS",
            fk_url_registry_id=url_id,
        )
        await s.execute(
            text(
                "UPDATE sch_fbref_infra.scrape_queue"
                " SET retry_count=4, locked_at=now() WHERE id=:id"
            ),
            {"id": queue_id},
        )
        await s.execute(
            text(
                "UPDATE sch_fbref_backend.tbl_player_urls"
                " SET retry_count=4 WHERE id=:id"
            ),
            {"id": url_id},
        )
        await s.commit()

    await record_job_failure(
        queue_id, "fatal", max_retries=5, session_factory=session_factory,
    )

    async with session_factory() as s:
        qr = (
            await s.execute(
                text(
                    "SELECT status, retry_count"
                    " FROM sch_fbref_infra.scrape_queue WHERE id=:id"
                ),
                {"id": queue_id},
            )
        ).one()
        ur = (
            await s.execute(
                text(
                    "SELECT status, retry_count"
                    " FROM sch_fbref_backend.tbl_player_urls WHERE id=:id"
                ),
                {"id": url_id},
            )
        ).one()
        assert qr.status == "FAILED"
        assert qr.retry_count == 5
        assert ur.status == "STALE"
        assert ur.retry_count == 5  # must match queue
