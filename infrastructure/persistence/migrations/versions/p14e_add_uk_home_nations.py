"""Add UK home nations to tbl_countries (England, Scotland, Wales, Northern Ireland)

These nations compete independently in football (FIFA/UEFA) but are not
sovereign states, so they are absent from standard ISO 3166-1 country tables.
They are added without flag URL or confederation FK.

Revision ID: p14e
Revises: p14d
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p14e"
down_revision: str | Sequence[str] | None = "p14d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROWS: list[tuple[str, str, str]] = [
    ("ENG", "England", "/en/country/ENG/England-Football"),
    ("SCO", "Scotland", "/en/country/SCO/Scotland-Football"),
    ("WAL", "Wales", "/en/country/WAL/Wales-Football"),
    ("NIR", "Northern Ireland", "/en/country/NIR/Northern-Ireland-Football"),
]


def upgrade() -> None:
    for country_id, country_name, country_url in _ROWS:
        op.execute(
            sa.text(
                "INSERT INTO sch_shared.tbl_countries "
                "(country_id, country_name, country_url) "
                "VALUES (:id, :name, :url) "
                "ON CONFLICT (country_id) DO NOTHING"
            ).bindparams(id=country_id, name=country_name, url=country_url)
        )


def downgrade() -> None:
    _ids = tuple(row[0] for row in _ROWS)
    # Use ANY syntax for PostgreSQL tuple matching with asyncpg
    op.execute(
        sa.text(
            "UPDATE sch_shared.tbl_player_info"
            " SET fk_country_birth = NULL"
            " WHERE fk_country_birth = ANY(:ids)"
        ).bindparams(ids=_ids)
    )
    op.execute(
        sa.text(
            "UPDATE sch_shared.tbl_player_info"
            " SET fk_national_team = NULL"
            " WHERE fk_national_team = ANY(:ids)"
        ).bindparams(ids=_ids)
    )
    for country_id, *_ in _ROWS:
        op.execute(
            sa.text(
                "DELETE FROM sch_shared.tbl_countries WHERE country_id = :id"
            ).bindparams(id=country_id)
        )
