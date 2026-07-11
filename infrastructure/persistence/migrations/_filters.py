"""Alembic autogenerate include_name callback.

Controls which database objects Alembic tracks during autogenerate scans.
Only schemas listed in _MANAGED_SCHEMAS are included; non-schema objects
(tables, columns, indexes, etc.) are always included.

Imported by env.py and passed as the include_name= argument to both
context.configure() calls (offline and online). Kept in a separate module
so tests can import the callback directly without triggering env.py's
top-level execution side effects (offline/online dispatch, Settings load).
"""

from collections.abc import MutableMapping
from typing import Literal

NameFilterType = Literal[
    "schema",
    "table",
    "column",
    "index",
    "unique_constraint",
    "foreign_key_constraint",
]

_MANAGED_SCHEMAS: frozenset[str] = frozenset(
    {
        "sch_infra",
        "sch_shared",
        "sch_football",
    }
)


def include_name(
    name: str | None,
    type_: NameFilterType,
    parent_names: MutableMapping[
        Literal["schema_name", "table_name", "schema_qualified_table_name"],
        str | None,
    ],
) -> bool:
    """Return True when Alembic should track the named database object.

    For schema-type objects, only schemas listed in _MANAGED_SCHEMAS are
    included. All other object types (table, column, index, etc.) are included
    unconditionally — the schema filter already gates them upstream.

    Args:
        name: Object name (schema name for type_="schema", table/column name
              for other types). May be None for some object types.
        type_: Alembic NameFilterType literal — "schema", "table", "column",
               "index", "unique_constraint", or "foreign_key_constraint".
        parent_names: Mapping of ancestor name keys provided by Alembic,
                      e.g. {"schema_name": "sch_infra"}.

    Returns:
        True if the object should be included in autogenerate; False otherwise.
    """
    if type_ == "schema":
        return name in _MANAGED_SCHEMAS
    return True
