"""Postgres map store: claims in our own tables (decision 0011).

Open it with the ingestor role to write, the reader role to read. Every query
runs in a client span to the `postgres` slot, so the self-map observes it.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras

from morphogen import telemetry
from morphogen.store.base import Identity, MapStore, Query

SCHEMA_SQL = Path(__file__).with_name("schema.sql")
COLUMNS = ("id", "key", "kind", "status", "environment", "level", "provenance", "confidence",
           "source_event_id", "valid_from", "valid_to", "recorded_at", "record_to", "retracted",
           "content")


class PostgresStore(MapStore):
    def __init__(self, dsn: str, slot: str = "ingestor") -> None:
        self.slot = slot
        self.conn = psycopg2.connect(dsn)
        self._lock = threading.RLock()
        self._depth = 0

    def ensure_schema(self) -> None:
        with self.transaction(), self._cursor("ensure_schema") as cur:
            cur.execute(SCHEMA_SQL.read_text())

    @contextmanager
    def transaction(self):
        with self._lock:
            self._depth += 1
            try:
                yield
                if self._depth == 1:
                    self.conn.commit()
            except BaseException:
                if self._depth == 1:
                    self.conn.rollback()
                raise
            finally:
                self._depth -= 1

    @contextmanager
    def _cursor(self, op: str):
        with telemetry.client_span(f"map.{op}", self.slot, "postgres", **{"db.system": "postgresql"}):
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                yield cur

    def _read(self, op: str, sql: str, args) -> list[dict]:
        with self.transaction(), self._cursor(op) as cur:
            cur.execute(sql, args)
            return [dict(r) for r in cur.fetchall()]

    def _open_row(self, ident: Identity) -> dict | None:
        rows = self._read(
            "open_row",
            f"SELECT {', '.join(COLUMNS)} FROM map.claims WHERE key=%s AND status=%s AND environment=%s"
            " AND valid_to IS NULL AND record_to IS NULL",
            ident,
        )
        return rows[0] if rows else None

    def _insert(self, rows: list[dict]) -> None:
        with self.transaction(), self._cursor("insert") as cur:
            psycopg2.extras.execute_values(
                cur,
                f"INSERT INTO map.claims ({', '.join(COLUMNS)}) VALUES %s",
                [tuple(psycopg2.extras.Json(r[c]) if c == "content" else r[c] for c in COLUMNS)
                 for r in rows],
            )

    def _close_record(self, row_ids: list[str], at: datetime) -> None:
        with self.transaction(), self._cursor("close_record") as cur:
            cur.execute("UPDATE map.claims SET record_to=%s WHERE id = ANY(%s::uuid[])", (at, row_ids))

    def _select(self, q: Query) -> list[dict]:
        where = ["valid_from <= coalesce(%(t)s, now())",
                 "(valid_to IS NULL OR valid_to > coalesce(%(t)s, now()))",
                 "recorded_at <= coalesce(%(r)s, now())",
                 "(record_to IS NULL OR record_to > coalesce(%(r)s, now()))"]
        args = {"t": q.valid_at, "r": q.recorded_at}
        for col in ("kind", "status", "environment"):
            if getattr(q, col) is not None:
                where.append(f"{col} = %({col})s")
                args[col] = getattr(q, col)
        if q.key_prefix is not None:
            where.append("starts_with(key, %(prefix)s)")
            args["prefix"] = q.key_prefix
        if not q.include_retracted:
            where.append("NOT retracted")
        return self._read(
            "select",
            f"SELECT {', '.join(COLUMNS)} FROM map.claims WHERE {' AND '.join(where)} ORDER BY key",
            args,
        )

    def _history(self, key: str) -> list[dict]:
        return self._read(
            "history",
            f"SELECT {', '.join(COLUMNS)} FROM map.claims WHERE key=%s ORDER BY valid_from, recorded_at",
            (key,),
        )

    def touch(self, keys: Iterable[str], at: datetime) -> None:
        keys = list(keys)
        if not keys:
            return
        with self.transaction(), self._cursor("touch") as cur:
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO map.seen (key, last_seen) VALUES %s ON CONFLICT (key) DO UPDATE"
                " SET last_seen = greatest(map.seen.last_seen, excluded.last_seen)",
                [(k, at) for k in keys],
            )

    def last_seen(self, keys: Iterable[str]) -> dict[str, datetime]:
        rows = self._read("last_seen", "SELECT key, last_seen FROM map.seen WHERE key = ANY(%s)",
                          (list(keys),))
        return {r["key"]: r["last_seen"] for r in rows}
