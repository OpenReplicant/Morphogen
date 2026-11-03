"""Postgres backend: the lists as tables or as graph labels, an edges table, an append-only evidence log.

Selected in morphogen.yaml:

    backends:
      default: postgres
      postgres:
        url: postgresql://morphogen@localhost:5432/morphogen   # or MORPHOGEN_POSTGRES_URL
        schema: morphogen
        layout: tables        # tables | labels

Two physical layouts, the same data:

- `tables`: one table per list (`systems`, `slots`, ...), each `(id text, data jsonb)`.
  A view `nodes (label, id, data)` unions them, so graph tools see each list as a label.
- `labels`: one table `nodes (label, id, data)`, the label being the list's name.
  A view per list (`systems`, `slots`, ...) selects its rows, so SQL tools see tables.

Either way `edges (src_label, src_id, field, dst_id)` holds every reference field
(ports.REF_FIELDS) and is rewritten on each put, so a graph extension that works over
existing tables, or a recursive query, can walk the map. `follow` is a recursive query.

`catalog (section, name, data)` mirrors catalogs.yaml (the file stays the source;
`sync_catalog` refreshes the table when the file changes).

The evidence log is a table whose rows a trigger refuses to update or delete, with
the same hash chain as the files backend, so `enforced_append_only` is true here.
Appends take a table lock, so concurrent writers get a single chain.

Driver: pg8000 (pure Python, BSD-3-Clause), an optional dependency:
`uv sync --extra postgres`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any
from urllib.parse import unquote, urlparse

from .backend_files import FilesLog, _matches, canonical, change_record, check_evidence
from .ports import KINDS, REF_FIELDS, TRUST

LAYOUTS = ("tables", "labels")
_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def connect(url: str):
    try:
        import pg8000.native
    except ImportError as e:  # the extra is optional
        raise RuntimeError("the postgres backend needs pg8000: uv sync --extra postgres") from e
    u = urlparse(url)
    if u.scheme not in ("postgresql", "postgres"):
        raise ValueError("backends.postgres.url must start with postgresql://")
    return pg8000.native.Connection(
        user=unquote(u.username or "postgres"), password=unquote(u.password) if u.password else None,
        host=u.hostname or "localhost", port=u.port or 5432, database=(u.path or "/postgres").lstrip("/") or "postgres")


def settings(cfg: dict) -> dict:
    pg = ((cfg.get("backends") or {}).get("postgres") or {})
    url = os.environ.get("MORPHOGEN_POSTGRES_URL") or pg.get("url")
    if not url:
        raise RuntimeError("the postgres backend needs backends.postgres.url or MORPHOGEN_POSTGRES_URL")
    schema, layout = pg.get("schema", "morphogen"), pg.get("layout", "tables")
    if not _IDENT.match(schema):
        raise ValueError(f"schema {schema!r}: lowercase letters, digits and underscores")
    if layout not in LAYOUTS:
        raise ValueError(f"layout must be one of {', '.join(LAYOUTS)}")
    return {"url": url, "schema": schema, "layout": layout}


class PostgresListStore:
    def __init__(self, conn, schema: str = "morphogen", layout: str = "tables", changes: "PostgresLog | None" = None):
        if layout not in LAYOUTS or not _IDENT.match(schema):
            raise ValueError("bad schema or layout")
        self.db, self.s, self.layout = conn, schema, layout
        self.changes = changes  # every write is recorded here, in the same transaction, when given
        self._create()
        vector = bool(self.db.run("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
        self.capabilities = {"concurrent_writers": True, "native_multi_hop": True, "vector_search": vector,
                             "layout": layout}

    # --- schema
    def _create(self) -> None:
        s = self.s
        self.db.run(f"CREATE SCHEMA IF NOT EXISTS {s}")
        existing = {r[0] for r in self.db.run(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = :s AND table_type = 'BASE TABLE'",
            s=s)}
        other = "nodes" if self.layout == "tables" else "systems"
        if other in existing:
            raise RuntimeError(f"schema {s} already uses the other layout; dump with one and load with the other")
        if self.layout == "tables":
            for k in KINDS:
                self.db.run(f"CREATE TABLE IF NOT EXISTS {s}.{k} (id text PRIMARY KEY, data jsonb NOT NULL)")
            union = " UNION ALL ".join(f"SELECT '{k}'::text AS label, id, data FROM {s}.{k}" for k in KINDS)
            self.db.run(f"CREATE OR REPLACE VIEW {s}.nodes AS {union}")
        else:
            self.db.run(f"CREATE TABLE IF NOT EXISTS {s}.nodes (label text NOT NULL, id text NOT NULL, "
                        f"data jsonb NOT NULL, PRIMARY KEY (label, id))")
            for k in KINDS:
                self.db.run(f"CREATE OR REPLACE VIEW {s}.{k} AS SELECT id, data FROM {s}.nodes WHERE label = '{k}'")
        self.db.run(f"CREATE TABLE IF NOT EXISTS {s}.edges (src_label text NOT NULL, src_id text NOT NULL, "
                    f"field text NOT NULL, dst_id text NOT NULL, PRIMARY KEY (src_label, src_id, field, dst_id))")
        self.db.run(f"CREATE INDEX IF NOT EXISTS edges_dst ON {s}.edges (dst_id)")
        self.db.run(f"CREATE TABLE IF NOT EXISTS {s}.catalog (section text NOT NULL, name text NOT NULL, "
                    f"data jsonb NOT NULL, PRIMARY KEY (section, name))")
        self.db.run(f"CREATE TABLE IF NOT EXISTS {s}.meta (key text PRIMARY KEY, value text NOT NULL)")

    def _check(self, kind: str) -> None:
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}; expected one of {', '.join(KINDS)}")

    def _rows(self, kind: str, id: str | None = None) -> list[dict]:
        self._check(kind)
        if self.layout == "tables":
            q, p = f"SELECT data FROM {self.s}.{kind}", {}
        else:
            q, p = f"SELECT data FROM {self.s}.nodes WHERE label = :k", {"k": kind}
        if id is not None:
            q += (" WHERE" if self.layout == "tables" else " AND") + " id = :id"
            p["id"] = id
        return [r[0] for r in self.db.run(q + " ORDER BY id", **p)]

    # --- the list-store port
    def get(self, kind: str, id: str) -> dict | None:
        rows = self._rows(kind, id)
        return rows[0] if rows else None

    def put(self, kind: str, entry: dict, by: str = "agent", reason: str | None = None) -> dict:
        return self._put(kind, entry, by, reason, "put")

    def _put(self, kind: str, entry: dict, by: str, reason: str | None, op: str,
             before: dict | None = None, known_before: bool = False) -> dict:
        self._check(kind)
        if not isinstance(entry, dict) or not entry.get("id"):
            raise ValueError("an entry needs a non-empty 'id'")
        id, data = str(entry["id"]), json.dumps(entry)
        self.db.run("START TRANSACTION")
        try:
            if not known_before:
                before = self.get(kind, id)
            if self.layout == "tables":
                self.db.run(f"INSERT INTO {self.s}.{kind} (id, data) VALUES (:id, CAST(:d AS jsonb)) "
                            "ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data", id=id, d=data)
            else:
                self.db.run(f"INSERT INTO {self.s}.nodes (label, id, data) VALUES (:k, :id, CAST(:d AS jsonb)) "
                            "ON CONFLICT (label, id) DO UPDATE SET data = EXCLUDED.data", k=kind, id=id, d=data)
            self.db.run(f"DELETE FROM {self.s}.edges WHERE src_label = :k AND src_id = :id", k=kind, id=id)
            for field in REF_FIELDS.get(kind, ()):
                v = entry.get(field)
                for dst in (v if isinstance(v, list) else [v] if v else []):
                    self.db.run(f"INSERT INTO {self.s}.edges VALUES (:k, :id, :f, :d) ON CONFLICT DO NOTHING",
                                k=kind, id=id, f=field, d=str(dst))
            if self.changes is not None and before != entry:
                self.changes.append_in_transaction(change_record(kind, entry, before, op, by, reason))
            self.db.run("COMMIT")
        except Exception:
            self.db.run("ROLLBACK")
            raise
        return entry

    def query(self, kind: str, where: dict[str, Any] | None = None) -> list[dict]:
        return [e for e in self._rows(kind) if _matches(e, where or {})]

    def follow(self, kind: str, id: str, field: str, hops: int = 1) -> list[dict]:
        """Entries reachable from `id` along `field`, nearest first, each once (a recursive query over edges)."""
        if self.get(kind, id) is None and not self.db.run(f"SELECT 1 FROM {self.s}.nodes WHERE id = :id", id=id):
            return []
        rows = self.db.run(
            f"""WITH RECURSIVE walk(id, depth) AS (
                    SELECT CAST(:start AS text), 0
                    UNION
                    SELECT e.dst_id, w.depth + 1 FROM {self.s}.edges e JOIN walk w ON e.src_id = w.id
                    WHERE e.field = :f AND w.depth < :hops)
                SELECT n.data, min(w.depth) AS d FROM walk w JOIN {self.s}.nodes n ON n.id = w.id
                WHERE w.depth > 0 AND w.id <> :start GROUP BY n.label, n.id, n.data ORDER BY d, n.id""",
            start=id, f=field, hops=max(int(hops), 0))
        return [r[0] for r in rows]

    def dump(self) -> dict[str, list[dict]]:
        return {k: self._rows(k) for k in KINDS}

    def load(self, data: dict[str, list[dict]], by: str = "operator") -> None:
        for kind, entries in data.items():
            self._check(kind)
            before = {e["id"]: e for e in self._rows(kind)}
            if self.layout == "tables":
                self.db.run(f"DELETE FROM {self.s}.{kind}")
            else:
                self.db.run(f"DELETE FROM {self.s}.nodes WHERE label = :k", k=kind)
            self.db.run(f"DELETE FROM {self.s}.edges WHERE src_label = :k", k=kind)
            for e in entries:
                self._put(kind, e, by, None, "load", before.get(e["id"]), known_before=True)

    def history(self, kind: str | None = None, id: str | None = None, limit: int = 50) -> list[dict]:
        """Recorded writes, newest first; empty when this store keeps no change log."""
        if self.changes is None:
            return []
        where = {k: v for k, v in (("list", kind), ("id", id)) if v}
        return self.changes.query(where=where, limit=limit)

    # --- graph extensions
    def pggraph_sql(self, graph: str = "morphogen") -> list[str]:
        """SQL that registers this map with pgGraph (the `graph` extension, evokoa/pggraph), per its API
        reference: each list's table as a node table keyed by `id`, and `edges` as an edge table once per
        target list, labelled by the reference field (rows whose target is in another list are left out).

        Written against pgGraph 1.2's documented API and not run against the extension here. Only the
        `tables` layout fits: pgGraph needs real tables with a single-column key, and `labels` has a
        composite key. Run the statements, then build the graph and enable sync as its docs describe.
        pgGraph resolves an edge-table row's source by a unique match across the registered node tables,
        so ids must be unique across lists; Morphogen's id prefixes (`type/`, `comp/`, `src/`) keep them so,
        but the list store does not enforce it.
        """
        if self.layout != "tables":
            raise RuntimeError("pgGraph needs the tables layout (a real table per list with a single-column id)")
        s = self.s
        stmts = [f"SELECT graph.add_table('{s}.{k}', 'id')" for k in KINDS]
        targets = sorted({t for t in KINDS for fields in REF_FIELDS.values() if fields})
        for t in targets:
            stmts.append(f"SELECT graph.add_edge('{s}.edges', 'src_id', '{s}.{t}', 'dst_id', 'ref', "
                         f"true, NULL, 'field')")
        return stmts

    # --- the catalog mirror
    def sync_catalog(self, catalog: dict) -> int:
        """Mirror catalogs.yaml into the catalog table when it changed. Returns rows written (0 if unchanged)."""
        digest = hashlib.sha256(canonical(catalog).encode()).hexdigest()
        if self.db.run(f"SELECT 1 FROM {self.s}.meta WHERE key = 'catalog' AND value = :v", v=digest):
            return 0
        self.db.run("START TRANSACTION")
        try:
            self.db.run(f"DELETE FROM {self.s}.catalog")
            n = 0
            for section, entries in (catalog or {}).items():
                for e in entries if isinstance(entries, list) else []:
                    if isinstance(e, dict) and e.get("name"):
                        self.db.run(f"INSERT INTO {self.s}.catalog VALUES (:s, :n, CAST(:d AS jsonb)) "
                                    "ON CONFLICT DO NOTHING", s=str(section), n=str(e["name"]), d=json.dumps(e))
                        n += 1
            self.db.run(f"INSERT INTO {self.s}.meta VALUES ('catalog', :v) ON CONFLICT (key) DO UPDATE "
                        "SET value = EXCLUDED.value", v=digest)
            self.db.run("COMMIT")
        except Exception:
            self.db.run("ROLLBACK")
            raise
        return n

    def catalog_rows(self, section: str | None = None) -> list[dict]:
        if section:
            return [r[0] for r in self.db.run(f"SELECT data FROM {self.s}.catalog WHERE section = :s ORDER BY name",
                                              s=section)]
        return [r[0] for r in self.db.run(f"SELECT data FROM {self.s}.catalog ORDER BY section, name")]


class PostgresLog:
    """An append-only table, with the files backend's hash chain. A trigger refuses UPDATE, DELETE and
    TRUNCATE, so append-only is enforced. The mechanism under every log (evidence, changes, journal)."""

    capabilities = {"enforced_append_only": True, "tamper_evident": True, "concurrent_writers": True}
    GENESIS = FilesLog.GENESIS
    _hash = staticmethod(FilesLog._hash)
    _check = FilesLog._check

    def __init__(self, conn, schema: str = "morphogen", table: str = "log"):
        if not _IDENT.match(schema) or not _IDENT.match(table):
            raise ValueError("bad schema or table")
        self.db, self.s, self.t = conn, schema, table
        self.path = f"postgres:{schema}.{table}"
        s, t = schema, table
        self.db.run(f"CREATE SCHEMA IF NOT EXISTS {s}")
        # `raw` is the canonical text the hash was computed over, so verification never depends on
        # how jsonb normalises numbers; `record` is the same record as jsonb, for queries.
        self.db.run(f"CREATE TABLE IF NOT EXISTS {s}.{t} (seq bigint PRIMARY KEY, hash text NOT NULL, "
                    f"prev text NOT NULL, raw text NOT NULL, record jsonb NOT NULL)")
        self.db.run(f"""CREATE OR REPLACE FUNCTION {s}.{t}_append_only() RETURNS trigger AS $$
                        BEGIN RAISE EXCEPTION '{t} is append-only'; END $$ LANGUAGE plpgsql""")
        self.db.run(f"DROP TRIGGER IF EXISTS {t}_append_only ON {s}.{t}")
        self.db.run(f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON {s}.{t} "
                    f"FOR EACH STATEMENT EXECUTE FUNCTION {s}.{t}_append_only()")

    def _records(self) -> list[dict]:
        return [json.loads(r[0]) for r in self.db.run(f"SELECT raw FROM {self.s}.{self.t} ORDER BY seq")]

    def append_in_transaction(self, record: dict) -> dict:
        """Append inside a transaction the caller has opened (so a list write and its change record commit
        together)."""
        self._check(record)
        self.db.run(f"LOCK TABLE {self.s}.{self.t} IN EXCLUSIVE MODE")
        last = self.db.run(f"SELECT seq, hash FROM {self.s}.{self.t} ORDER BY seq DESC LIMIT 1")
        rec = dict(record)
        rec["seq"] = (last[0][0] + 1) if last else 1
        rec["at"] = rec.get("at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rec["prev"] = last[0][1] if last else self.GENESIS
        rec.pop("hash", None)
        rec["hash"] = self._hash(rec)
        raw = canonical(rec)
        self.db.run(f"INSERT INTO {self.s}.{self.t} VALUES (:q, :h, :p, :raw, CAST(:js AS jsonb))",
                    q=rec["seq"], h=rec["hash"], p=rec["prev"], raw=raw, js=raw)
        return rec

    def append(self, record: dict) -> dict:
        self.db.run("START TRANSACTION")
        try:
            rec = self.append_in_transaction(record)
            self.db.run("COMMIT")
        except Exception:
            self.db.run("ROLLBACK")
            raise
        return rec

    verify = FilesLog.verify
    query = FilesLog.query

    def dump(self) -> list[dict]:
        return self._records()


class PostgresEvidenceLog(PostgresLog):
    """Claims with their support, in the `evidence` table."""

    def _check(self, record: dict) -> None:
        check_evidence(record)

    def __init__(self, conn, schema: str = "morphogen"):
        super().__init__(conn, schema, "evidence")
