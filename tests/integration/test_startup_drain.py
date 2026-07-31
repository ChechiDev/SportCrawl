"""Integration tests for _startup_drain against a real PostgreSQL database."""
from __future__ import annotations

import asyncio

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from infrastructure.persistence.repositories.player_info_queue import record_job_failure
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
            "INSERT INTO sch_fbref_shared.tbl_players (player_id, full_name)"
            " VALUES (:pid, :name) ON CONFLICT DO NOTHING"
        ),
        {"pid": player_id, "name": player_id},
    )
    await session.flush()


async def _insert_player_url(session, *, fk_player: str, url: str, status: str = "PENDING", priority: int = 5) -> int:
    result = await session.execute(
        text(
            "INSERT INTO sch_fbref_backend.tbl_player_urls"
            " (fk_player, url_type, url, status, next_scrape_at, priority)"
            " VALUES (:fk_player, 'profile', :url, :status, now() - interval '1 hour', :priority)"
            " RETURNING id"
        ),
        {"fk_player": fk_player, "url": url, "status": status, "priority": priority},
    )
    row = result.one()
    await session.flush()
    return row[0]


async def _insert_queue_row(session, *, url: str, status: str, fk_url_registry_id=None) -> int:
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
        q = "SELECT COUNT(*) FROM sch_fbref_infra.scrape_queue WHERE job_type = 'player_info'"
        params: dict = {}
        if url is not None:
            q += " AND url = :url"
            params["url"] = url
        if status is not None:
            q += " AND status = :status"
            params["status"] = status
        result = await s.execute(text(q), params)
        return result.scalar_one()


async def test_no_due_url_no_insert(async_session, session_factory):
    # No player_url rows due → drain returns 0
    count = await _startup_drain(session_factory, batch_size=100)
    assert count == 0
    total = await _count_queue_rows(session_factory)
    assert total == 0


async def test_pending_url_inserts_queue_row(async_session, session_factory):
    player_id = "test_pending_url_p1"
    url = f"https://fbref.com/en/players/{player_id}/player"
    await _insert_player(async_session, player_id)
    await _insert_player_url(async_session, fk_player=player_id, url=url)
    await async_session.commit()

    count = await _startup_drain(session_factory, batch_size=100)
    assert count == 1

    total = await _count_queue_rows(session_factory, url=url, status="PENDING")
    assert total == 1


async def test_existing_pending_queue_not_reactivated(async_session, session_factory):
    player_id = "test_existing_pending_p2"
    url = f"https://fbref.com/en/players/{player_id}/player"
    await _insert_player(async_session, player_id)
    url_id = await _insert_player_url(async_session, fk_player=player_id, url=url)
    await _insert_queue_row(async_session, url=url, status="PENDING", fk_url_registry_id=url_id)
    await async_session.commit()

    count = await _startup_drain(session_factory, batch_size=100)
    assert count == 0

    total = await _count_queue_rows(session_factory, url=url, status="PENDING")
    assert total == 1


async def test_existing_in_progress_not_modified(async_session, session_factory):
    player_id = "test_in_progress_p3"
    url = f"https://fbref.com/en/players/{player_id}/player"
    await _insert_player(async_session, player_id)
    url_id = await _insert_player_url(async_session, fk_player=player_id, url=url)
    await _insert_queue_row(async_session, url=url, status="IN_PROGRESS", fk_url_registry_id=url_id)
    await async_session.commit()

    count = await _startup_drain(session_factory, batch_size=100)
    assert count == 0

    total = await _count_queue_rows(session_factory, url=url, status="IN_PROGRESS")
    assert total == 1


async def test_existing_done_reactivated_exactly_once(async_session, session_factory):
    player_id = "test_done_reactivate_p4"
    url = f"https://fbref.com/en/players/{player_id}/player"
    await _insert_player(async_session, player_id)
    url_id = await _insert_player_url(async_session, fk_player=player_id, url=url)
    await _insert_queue_row(async_session, url=url, status="DONE", fk_url_registry_id=url_id)
    await async_session.commit()

    count = await _startup_drain(session_factory, batch_size=100)
    assert count == 1
    # second call should not reactivate again
    count2 = await _startup_drain(session_factory, batch_size=100)
    assert count2 == 0


async def test_existing_failed_not_modified(async_session, session_factory):
    player_id = "test_failed_p5"
    url = f"https://fbref.com/en/players/{player_id}/player"
    await _insert_player(async_session, player_id)
    url_id = await _insert_player_url(async_session, fk_player=player_id, url=url)
    await _insert_queue_row(async_session, url=url, status="FAILED", fk_url_registry_id=url_id)
    await async_session.commit()

    count = await _startup_drain(session_factory, batch_size=100)
    assert count == 0

    total = await _count_queue_rows(session_factory, url=url, status="FAILED")
    assert total == 1


async def test_batch_size_limits_rows_per_call(async_session, session_factory):
    base = "test_batch_size_p6"
    for i in range(5):
        pid = f"{base}_{i}"
        url = f"https://fbref.com/en/players/{pid}/player"
        await _insert_player(async_session, pid)
        await _insert_player_url(async_session, fk_player=pid, url=url)
    await async_session.commit()

    c1 = await _startup_drain(session_factory, batch_size=2)
    assert c1 == 2
    c2 = await _startup_drain(session_factory, batch_size=2)
    assert c2 == 2
    c3 = await _startup_drain(session_factory, batch_size=2)
    assert c3 == 1
    c4 = await _startup_drain(session_factory, batch_size=2)
    assert c4 == 0


async def test_large_drain_terminates(async_session, session_factory):
    base = "test_large_drain_p7"
    for i in range(25):
        pid = f"{base}_{i}"
        url = f"https://fbref.com/en/players/{pid}/player"
        await _insert_player(async_session, pid)
        await _insert_player_url(async_session, fk_player=pid, url=url)
    await async_session.commit()

    total = 0
    for _ in range(10):  # safety cap
        n = await _startup_drain(session_factory, batch_size=10)
        total += n
        if n == 0:
            break
    assert total == 25


async def test_ordering_by_priority(async_session, session_factory):
    base = "test_priority_order_p8"
    urls = []
    for i, priority in enumerate([10, 1, 5]):
        pid = f"{base}_{i}"
        url = f"https://fbref.com/en/players/{pid}/player"
        await _insert_player(async_session, pid)
        await _insert_player_url(async_session, fk_player=pid, url=url, priority=priority)
        urls.append((priority, url))
    await async_session.commit()

    # drain 1 at a time, expect priority=1 (lowest number = highest priority) first
    c = await _startup_drain(session_factory, batch_size=1)
    assert c == 1

    # Check that the row inserted is the one with priority=1
    async with session_factory() as s:
        result = await s.execute(
            text(
                "SELECT sq.url FROM sch_fbref_infra.scrape_queue sq"
                " JOIN sch_fbref_backend.tbl_player_urls bpu ON sq.fk_url_registry_id = bpu.id"
                " WHERE sq.job_type = 'player_info' AND sq.status = 'PENDING'"
                " ORDER BY bpu.priority ASC LIMIT 1"
            )
        )
        row = result.one_or_none()
        assert row is not None
        assert "test_priority_order_p8_1" in row[0]  # the pid with priority=1


async def test_concurrent_drains_no_duplicates(async_session, session_factory):
    base = "test_concurrent_p9"
    for i in range(5):
        pid = f"{base}_{i}"
        url = f"https://fbref.com/en/players/{pid}/player"
        await _insert_player(async_session, pid)
        await _insert_player_url(async_session, fk_player=pid, url=url)
    await async_session.commit()

    results = await asyncio.gather(
        _startup_drain(session_factory, batch_size=5),
        _startup_drain(session_factory, batch_size=5),
    )
    total = sum(results)
    assert total == 5  # no duplicates


async def test_legacy_null_fk_does_not_block_due_url(async_session, session_factory):
    # url_A has a queue row with NULL fk — legacy row
    url_a = "https://fbref.com/en/players/legacy_null_fk_pA/player"
    await _insert_queue_row(async_session, url=url_a, status="PENDING", fk_url_registry_id=None)

    # url_B is a new due player_url row
    pid_b = "test_legacy_null_fk_pB"
    url_b = f"https://fbref.com/en/players/{pid_b}/player"
    await _insert_player(async_session, pid_b)
    await _insert_player_url(async_session, fk_player=pid_b, url=url_b)
    await async_session.commit()

    count = await _startup_drain(session_factory, batch_size=100)
    assert count == 1  # only url_B inserted

    total_b = await _count_queue_rows(session_factory, url=url_b, status="PENDING")
    assert total_b == 1

    # url_A's NULL FK row is untouched
    total_a = await _count_queue_rows(session_factory, url=url_a)
    assert total_a == 1


async def test_retryable_transition(async_session, session_factory):
    from sqlalchemy import text as _text

    player_id = "test_retryable_p10"
    url = f"https://fbref.com/en/players/{player_id}/player"
    await _insert_player(async_session, player_id)
    url_id = await _insert_player_url(async_session, fk_player=player_id, url=url)
    queue_id = await _insert_queue_row(async_session, url=url, status="IN_PROGRESS", fk_url_registry_id=url_id)
    # set retry_count=0 explicitly
    await async_session.execute(
        _text("UPDATE sch_fbref_infra.scrape_queue SET retry_count=0, locked_at=now() WHERE id=:id"),
        {"id": queue_id},
    )
    await async_session.commit()

    await record_job_failure(queue_id, "test error", max_retries=5, session_factory=session_factory)

    async with session_factory() as s:
        result = await s.execute(
            _text("SELECT status, retry_count FROM sch_fbref_infra.scrape_queue WHERE id=:id"),
            {"id": queue_id},
        )
        row = result.one()
        assert row[0] == "PENDING"
        assert row[1] == 1

        result2 = await s.execute(
            _text("SELECT retry_count FROM sch_fbref_backend.tbl_player_urls WHERE id=:id"),
            {"id": url_id},
        )
        url_row = result2.one()
        assert url_row[0] == 1


async def test_terminal_transition(async_session, session_factory):
    from sqlalchemy import text as _text

    player_id = "test_terminal_p11"
    url = f"https://fbref.com/en/players/{player_id}/player"
    await _insert_player(async_session, player_id)
    url_id = await _insert_player_url(async_session, fk_player=player_id, url=url)
    queue_id = await _insert_queue_row(async_session, url=url, status="IN_PROGRESS", fk_url_registry_id=url_id)
    # set retry_count=4 so next failure (5) hits ceiling=5
    await async_session.execute(
        _text("UPDATE sch_fbref_infra.scrape_queue SET retry_count=4, locked_at=now() WHERE id=:id"),
        {"id": queue_id},
    )
    await async_session.commit()

    await record_job_failure(queue_id, "fatal error", max_retries=5, session_factory=session_factory)

    async with session_factory() as s:
        result = await s.execute(
            _text("SELECT status, retry_count FROM sch_fbref_infra.scrape_queue WHERE id=:id"),
            {"id": queue_id},
        )
        row = result.one()
        assert row[0] == "FAILED"
        assert row[1] == 5

        result2 = await s.execute(
            _text("SELECT status FROM sch_fbref_backend.tbl_player_urls WHERE id=:id"),
            {"id": url_id},
        )
        url_row = result2.one()
        assert url_row[0] == "STALE"
