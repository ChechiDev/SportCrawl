"""BackendUrlRepository — manages URL scheduling tables in sch_fbref_backend.

Tables managed (all share the same column layout):
    tbl_player_urls
    tbl_team_urls
    tbl_competition_urls
    tbl_country_urls
    tbl_country_squad_urls

The caller owns the transaction; this repository never commits.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

_VALID_TABLES: frozenset[str] = frozenset(
    {
        "tbl_player_urls",
        "tbl_team_urls",
        "tbl_competition_urls",
        "tbl_country_urls",
        "tbl_country_squad_urls",
    }
)

_SCHEMA = "sch_fbref_backend"


def _qualified(table: str) -> str:
    """Return schema-qualified table name after whitelist validation."""
    if table not in _VALID_TABLES:
        raise ValueError(
            f"Unknown backend URL table: {table!r}. "
            f"Valid tables: {sorted(_VALID_TABLES)}"
        )
    return f"{_SCHEMA}.{table}"


@dataclass
class BackendUrlRow:
    id: int
    url: str
    url_type: str
    priority: int
    next_scrape_at: datetime


class BackendUrlRepository:
    """Read/write access to sch_fbref_backend URL scheduling tables.

    All SQL uses sa.text() with named bind parameters. Table names are
    validated against a whitelist before interpolation into SQL strings.
    The caller owns the transaction and must call session.commit().
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def fetch_due_rows(
        self,
        table: str,
        limit: int = 100,
    ) -> list[BackendUrlRow]:
        """Return rows due for scraping (ACTIVE and past next_scrape_at).

        Args:
            table: One of the five valid backend URL table names.
            limit: Maximum number of rows to return (default 100).

        Returns:
            List of BackendUrlRow ordered by priority ASC, next_scrape_at ASC.

        Raises:
            ValueError: if table is not a known backend URL table.
        """
        qualified = _qualified(table)
        stmt = sa.text(
            f"SELECT id, url, url_type, priority, next_scrape_at"  # noqa: S608
            f" FROM {qualified}"
            f" WHERE status = 'ACTIVE'"
            f"   AND next_scrape_at <= now()"
            f" ORDER BY priority ASC, next_scrape_at ASC"
            f" LIMIT :limit"
        )
        result = await self._session.execute(stmt, {"limit": limit})
        rows = result.fetchall()
        return [
            BackendUrlRow(
                id=row.id,
                url=row.url,
                url_type=row.url_type,
                priority=row.priority,
                next_scrape_at=row.next_scrape_at,
            )
            for row in rows
        ]

    async def mark_scraped(
        self,
        table: str,
        row_id: int,
        *,
        status: str = "SUCCESS",
    ) -> None:
        """Record a successful scrape and advance the next_scrape_at schedule.

        Sets last_scraped_at and last_scrape_status, advances next_scrape_at
        by cadence_hours, resets retry_count to 0, and clears last_error.
        Does NOT modify the lifecycle `status` column.

        Args:
            table: One of the five valid backend URL table names.
            row_id: Primary key of the row to update.
            status: Scrape outcome label (default "SUCCESS").

        Raises:
            ValueError: if table is not a known backend URL table.
        """
        qualified = _qualified(table)
        stmt = sa.text(
            f"UPDATE {qualified}"
            f" SET last_scraped_at = now(),"
            f"     last_scrape_status = :scrape_status,"
            f"     next_scrape_at = now() + cadence_hours * interval '1 hour',"
            f"     retry_count = 0,"
            f"     last_error = NULL,"
            f"     updated_at = now()"
            f" WHERE id = :row_id"
        )
        await self._session.execute(
            stmt,
            {"scrape_status": status, "row_id": row_id},
        )

    async def mark_failed(
        self,
        table: str,
        row_id: int,
        *,
        error: str,
    ) -> None:
        """Record a failed scrape and optionally transition the row to STALE.

        Increments retry_count and records the error. When retry_count reaches
        5 the lifecycle status is set to 'STALE' so the row stops being
        fetched as due. next_scrape_at is intentionally not changed.

        Args:
            table: One of the five valid backend URL table names.
            row_id: Primary key of the row to update.
            error: Error message or traceback excerpt to persist.

        Raises:
            ValueError: if table is not a known backend URL table.
        """
        qualified = _qualified(table)
        stmt = sa.text(
            f"UPDATE {qualified}"
            f" SET last_scrape_status = 'FAILURE',"
            f"     retry_count = retry_count + 1,"
            f"     last_error = :error,"
            f"     status = CASE WHEN retry_count + 1 >= 5 THEN 'STALE' ELSE status END,"
            f"     updated_at = now()"
            f" WHERE id = :row_id"
        )
        await self._session.execute(
            stmt,
            {"error": error, "row_id": row_id},
        )
