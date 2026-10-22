"""Map store: the slot behind which claims are kept (decision 0011).

`open_store()` returns the configured provider: Postgres when
MORPHOGEN_DATABASE_URL is set, otherwise an in-process memory store.
"""

from __future__ import annotations

import os

from morphogen.store.base import ChangeSet, MapStore, Query
from morphogen.store.memory import MemoryStore

__all__ = ["ChangeSet", "MapStore", "MemoryStore", "Query", "open_store"]


def open_store(dsn: str | None = None) -> MapStore:
    dsn = dsn or os.environ.get("MORPHOGEN_DATABASE_URL")
    if not dsn:
        return MemoryStore()
    from morphogen.store.postgres import PostgresStore

    return PostgresStore(dsn)
