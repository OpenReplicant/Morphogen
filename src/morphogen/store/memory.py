"""In-process map store: tests and single-process development. Not durable."""

from __future__ import annotations

import threading
from collections.abc import Iterable
from datetime import datetime

from morphogen.store.base import Identity, MapStore, Query, visible


class MemoryStore(MapStore):
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.seen: dict[str, datetime] = {}
        self._lock = threading.RLock()

    def transaction(self):
        return self._lock

    def _open_row(self, ident: Identity) -> dict | None:
        key, status, env = ident
        for r in reversed(self.rows):
            if (r["key"], r["status"], r["environment"]) == (key, status, env) \
                    and r["record_to"] is None and r["valid_to"] is None:
                return r
        return None

    def _insert(self, rows: list[dict]) -> None:
        self.rows += [dict(r) for r in rows]

    def _close_record(self, row_ids: list[str], at: datetime) -> None:
        for r in self.rows:
            if r["id"] in row_ids:
                r["record_to"] = at

    def _select(self, q: Query) -> list[dict]:
        with self._lock:
            return sorted((r for r in self.rows if visible(r, q)), key=lambda r: r["key"])

    def _history(self, key: str) -> list[dict]:
        return sorted((r for r in self.rows if r["key"] == key),
                      key=lambda r: (r["valid_from"], r["recorded_at"]))

    def touch(self, keys: Iterable[str], at: datetime) -> None:
        with self._lock:
            for k in keys:
                if k not in self.seen or self.seen[k] < at:
                    self.seen[k] = at

    def last_seen(self, keys: Iterable[str]) -> dict[str, datetime]:
        return {k: self.seen[k] for k in keys if k in self.seen}
