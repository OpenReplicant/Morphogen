"""The store: the lists and the three logs in one SQL database, through SQLAlchemy Core.

SQLite by default (one file, Python's own driver); Postgres when morphogen.yaml
gives a URL. The same code and the same tables serve both:

- one table per list (`systems`, `slots`, `types`, `sources`, `components`),
  each `(id, data)` with `data` as JSON (jsonb on Postgres);
- `edges (src_label, src_id, field, dst_id)`: every reference field
  (ports.REF_FIELDS), rewritten in the same transaction as each write;
- `catalog (section, name, data)`, a mirror of catalogs.yaml (the file stays
  the source), and `meta (key, value)`;
- three logs, `evidence`, `changes` and `journal`, each
  `(seq, hash, prev, raw, record)`: hash-chained, and triggers refuse UPDATE
  and DELETE (and TRUNCATE on Postgres).

A list write and its change record commit in one transaction. Appends take
the database's write lock (SQLite: BEGIN IMMEDIATE; Postgres: a table lock),
so concurrent writers get one chain.

JSONL is the format for publishing a map (`export_lists`) and for the seed
lists; mounted maps are read from it (maps.py).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import (JSON, BigInteger, Column, Index, Integer, MetaData, Table, Text, column, create_engine,
                        delete, event, select, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .ports import KINDS, REF_FIELDS, TRUST

LOGS = ("evidence", "changes", "journal")
GENESIS = "0" * 64
JSONT = JSON().with_variant(JSONB(), "postgresql")
_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def record_hash(record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(canonical(body).encode()).hexdigest()


def matches(entry: dict, where: dict[str, Any]) -> bool:
    """A list or log query: equal, `~text` for a case-insensitive substring, or membership in a list."""
    for key, want in where.items():
        have = entry.get(key)
        if isinstance(want, str) and want.startswith("~"):
            if want[1:].lower() not in canonical(have).lower():
                return False
        elif isinstance(have, list) and not isinstance(want, list):
            if want not in have:
                return False
        elif have != want:
            return False
    return True


def check_record(record: dict) -> None:
    if not isinstance(record, dict):
        raise ValueError("a log record is a mapping")


def check_evidence(record: dict) -> None:
    """What every evidence record needs."""
    check_record(record)
    if record.get("trust") not in TRUST:
        raise ValueError(f"trust must be one of {', '.join(TRUST)}")
    if not record.get("claim") or not record.get("by"):
        raise ValueError("evidence needs 'claim' and 'by'")


def change_record(kind: str, entry: dict, before: dict | None, op: str, by: str, reason: str | None) -> dict:
    """What the change log records for one write to a list."""
    return {"op": op, "list": kind, "id": entry["id"], "before": record_hash(before) if before else None,
            "after": record_hash(entry), "entry": entry, "by": by, **({"reason": reason} if reason else {})}


# --- the database

def _engine(url: str):
    if url.startswith("sqlite"):
        eng = create_engine(url, connect_args={"timeout": 30})

        @event.listens_for(eng, "connect")
        def _connect(dbapi, _):
            dbapi.isolation_level = None  # the driver issues no BEGIN of its own; we do, below
            cur = dbapi.cursor()
            cur.execute("PRAGMA journal_mode=WAL")  # readers do not wait for the writer
            cur.close()

        @event.listens_for(eng, "begin")
        def _begin(conn):
            conn.exec_driver_sql("BEGIN IMMEDIATE")  # take the write lock up front: one chain per log

        return eng
    parts = urlsplit(url)
    if parts.scheme in ("postgres", "postgresql"):  # the plain form; pg8000 is the driver Morphogen uses
        url = urlunsplit(parts._replace(scheme="postgresql+pg8000"))
    try:
        return create_engine(url, pool_pre_ping=True)
    except ModuleNotFoundError as e:
        raise RuntimeError("the postgres backend needs pg8000: uv sync --extra postgres") from e


class Database:
    """One database: the lists, the edges, the catalog mirror and the three logs."""

    def __init__(self, url: str, schema: str | None = None):
        self.url = url
        self.engine = _engine(url)
        self.dialect = self.engine.dialect.name
        if self.dialect == "postgresql":
            schema = schema or "morphogen"
            if not _IDENT.match(schema):
                raise ValueError(f"schema {schema!r}: lowercase letters, digits and underscores")
        else:
            schema = None  # SQLite has one namespace per file
        self.schema = schema
        md = MetaData(schema=schema)
        self.lists = {k: Table(k, md, Column("id", Text, primary_key=True), Column("data", JSONT, nullable=False))
                      for k in KINDS}
        self.edges = Table("edges", md, Column("src_label", Text, primary_key=True),
                           Column("src_id", Text, primary_key=True), Column("field", Text, primary_key=True),
                           Column("dst_id", Text, primary_key=True), Index("edges_dst", "dst_id"))
        self.catalog = Table("catalog", md, Column("section", Text, primary_key=True),
                             Column("name", Text, primary_key=True), Column("data", JSONT, nullable=False))
        self.meta = Table("meta", md, Column("key", Text, primary_key=True), Column("value", Text, nullable=False))
        self.logs = {n: Table(n, md, Column("seq", BigInteger, primary_key=True, autoincrement=False),
                              Column("hash", Text, nullable=False), Column("prev", Text, nullable=False),
                              Column("raw", Text, nullable=False), Column("record", JSONT, nullable=False))
                     for n in LOGS}
        self._create(md)

    def q(self, name: str) -> str:
        return f"{self.schema}.{name}" if self.schema else name

    def _create(self, md: MetaData) -> None:
        with self.engine.begin() as c:
            if self.schema:
                c.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")
                kind = c.execute(text("SELECT table_type FROM information_schema.tables "
                                      "WHERE table_schema = :s AND table_name = 'nodes'"), {"s": self.schema}).scalar()
                if kind == "BASE TABLE":
                    raise RuntimeError(f"schema {self.schema} uses the `labels` layout, which Morphogen 0.3 no longer "
                                       "has; dump it with 0.2 and load it into a new schema")
        md.create_all(self.engine)
        with self.engine.begin() as c:
            if self.dialect == "postgresql":
                for t in LOGS:
                    fn = self.q(f"{t}_append_only")
                    c.exec_driver_sql(f"CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger AS $$ "
                                      f"BEGIN RAISE EXCEPTION '{t} is append-only'; END $$ LANGUAGE plpgsql")
                    c.exec_driver_sql(f"DROP TRIGGER IF EXISTS {t}_append_only ON {self.q(t)}")
                    c.exec_driver_sql(f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE OR TRUNCATE "
                                      f"ON {self.q(t)} FOR EACH STATEMENT EXECUTE FUNCTION {fn}()")
            else:
                for t in LOGS:
                    for op in ("UPDATE", "DELETE"):
                        c.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS {t}_no_{op.lower()} BEFORE {op} ON {t} "
                                          f"BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END")

    def upsert(self, table: Table, row: dict, keys: list[str]):
        ins = (pg_insert if self.dialect == "postgresql" else sqlite_insert)(table).values(**row)
        rest = {k: ins.excluded[k] for k in row if k not in keys}
        return ins.on_conflict_do_update(index_elements=keys, set_=rest) if rest else ins.on_conflict_do_nothing()

    def lock(self, c, table: Table) -> None:
        """Hold the write lock on `table` until the transaction ends (SQLite already holds it)."""
        if self.dialect == "postgresql":
            c.exec_driver_sql(f"LOCK TABLE {self.q(table.name)} IN EXCLUSIVE MODE")

    def drop(self) -> None:
        """Remove everything (tests and scratch databases only)."""
        with self.engine.begin() as c:
            if self.schema:
                c.exec_driver_sql(f"DROP SCHEMA IF EXISTS {self.schema} CASCADE")
        self.engine.dispose()


# --- the logs

class Log:
    """An append-only, hash-chained log: each record carries the hash of the one before it, and the
    database refuses to change or delete a row. `raw` is the canonical text the hash was computed over,
    so verifying never depends on how the database stores JSON."""

    capabilities = {"enforced_append_only": True, "tamper_evident": True, "concurrent_writers": True}
    GENESIS = GENESIS

    def __init__(self, db: Database, name: str, check=check_record):
        self.db, self.name, self.table, self._check = db, name, db.logs[name], check
        self.path = f"postgres:{db.q(name)}" if db.schema else f"{db.url}#{name}"

    def _records(self) -> list[dict]:
        with self.db.engine.connect() as c:
            return [json.loads(r) for r in c.execute(select(self.table.c.raw).order_by(self.table.c.seq)).scalars()]

    def append_in(self, c, record: dict) -> dict:
        """Append inside the caller's transaction (a list write and its change record commit together)."""
        self._check(record)
        self.db.lock(c, self.table)
        last = c.execute(select(self.table.c.seq, self.table.c.hash).order_by(self.table.c.seq.desc())
                         .limit(1)).first()
        rec = dict(record)
        rec["seq"] = (last[0] + 1) if last else 1
        rec["at"] = rec.get("at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rec["prev"] = last[1] if last else GENESIS
        rec.pop("hash", None)
        rec["hash"] = record_hash(rec)
        self._insert(c, rec)
        return rec

    def _insert(self, c, rec: dict) -> None:
        c.execute(self.table.insert().values(seq=rec["seq"], hash=rec["hash"], prev=rec["prev"],
                                             raw=canonical(rec), record=rec))

    def append(self, record: dict) -> dict:
        with self.db.engine.begin() as c:
            return self.append_in(c, record)

    def verify(self) -> tuple[bool, int | None]:
        prev = GENESIS
        for i, rec in enumerate(self._records(), start=1):
            if rec.get("prev") != prev or rec.get("seq") != i or record_hash(rec) != rec.get("hash"):
                return False, i
            prev = rec["hash"]
        return True, None

    def query(self, contains: str | None = None, by: str | None = None, limit: int = 20,
              where: dict[str, Any] | None = None) -> list[dict]:
        """Newest first. `where` matches fields as list queries do."""
        out = []
        for rec in reversed(self._records()):
            if by and rec.get("by") != by:
                continue
            if contains and contains.lower() not in canonical(rec).lower():
                continue
            if where and not matches(rec, where):
                continue
            out.append(rec)
            if len(out) >= limit:
                break
        return out

    def dump(self) -> list[dict]:
        return self._records()

    def import_jsonl(self, path: Path) -> int:
        """Copy an older JSONL log in as it is (its own seq, prev and hash), into an empty log."""
        rows = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
        with self.db.engine.begin() as c:
            if c.execute(select(self.table.c.seq).limit(1)).first():
                raise RuntimeError(f"{self.name} is not empty")
            for rec in rows:
                self._insert(c, rec)
        return len(rows)


# --- the lists

class Lists:
    """The list-store port (ports.ListStore) on the database."""

    def __init__(self, db: Database, changes: Log | None = None):
        self.db, self.changes = db, changes  # every write is recorded in `changes`, in the same transaction
        vector = False
        if db.dialect == "postgresql":
            with db.engine.connect() as c:
                vector = bool(c.exec_driver_sql("SELECT 1 FROM pg_extension WHERE extname = 'vector'").first())
        self.capabilities = {"concurrent_writers": True, "native_multi_hop": True, "vector_search": vector,
                             "database": db.dialect}

    def _table(self, kind: str) -> Table:
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}; expected one of {', '.join(KINDS)}")
        return self.db.lists[kind]

    def _rows(self, c, kind: str, id: str | None = None) -> list[dict]:
        t = self._table(kind)
        q = select(t.c.data).order_by(t.c.id)
        return list(c.execute(q.where(t.c.id == id) if id is not None else q).scalars())

    def get(self, kind: str, id: str) -> dict | None:
        with self.db.engine.connect() as c:
            rows = self._rows(c, kind, id)
        return rows[0] if rows else None

    def put(self, kind: str, entry: dict, by: str = "agent", reason: str | None = None) -> dict:
        t = self._table(kind)
        if not isinstance(entry, dict) or not entry.get("id"):
            raise ValueError("an entry needs a non-empty 'id'")
        with self.db.engine.begin() as c:
            before = (self._rows(c, kind, str(entry["id"])) or [None])[0]
            self._write(c, kind, t, entry)
            if self.changes is not None and before != entry:
                self.changes.append_in(c, change_record(kind, entry, before, "put", by, reason))
        return entry

    def _write(self, c, kind: str, t: Table, entry: dict) -> None:
        id = str(entry["id"])
        c.execute(self.db.upsert(t, {"id": id, "data": entry}, ["id"]))
        e = self.db.edges
        c.execute(delete(e).where(e.c.src_label == kind, e.c.src_id == id))
        for field in REF_FIELDS.get(kind, ()):
            v = entry.get(field)
            for dst in sorted({str(d) for d in (v if isinstance(v, list) else [v] if v else [])}):
                c.execute(e.insert().values(src_label=kind, src_id=id, field=field, dst_id=dst))

    def query(self, kind: str, where: dict[str, Any] | None = None) -> list[dict]:
        with self.db.engine.connect() as c:
            return [e for e in self._rows(c, kind) if matches(e, where or {})]

    def follow(self, kind: str, id: str, field: str, hops: int = 1) -> list[dict]:
        """Entries reachable from `id` along `field`, nearest first, each once (a recursive query over edges)."""
        edges = self.db.q("edges")
        nodes = "(" + " UNION ALL ".join(f"SELECT CAST('{k}' AS TEXT) AS label, id, data FROM {self.db.q(k)}"
                                         for k in KINDS) + ")"
        with self.db.engine.connect() as c:
            if not c.execute(text(f"SELECT 1 FROM {nodes} n WHERE n.id = :id"), {"id": id}).first():
                return []
            q = text(f"""WITH RECURSIVE walk(id, depth) AS (
                    SELECT CAST(:start AS TEXT), 0
                    UNION
                    SELECT e.dst_id, w.depth + 1 FROM {edges} e JOIN walk w ON e.src_id = w.id
                    WHERE e.field = :f AND w.depth < :hops)
                SELECT n.data AS data, min(w.depth) AS d FROM walk w JOIN {nodes} n ON n.id = w.id
                WHERE w.depth > 0 AND w.id <> :start GROUP BY n.label, n.id, n.data ORDER BY d, n.id"""
                     ).columns(column("data", JSONT), column("d", Integer))
            return list(c.execute(q, {"start": id, "f": field, "hops": max(int(hops), 0)}).scalars())

    def dump(self) -> dict[str, list[dict]]:
        with self.db.engine.connect() as c:
            return {k: self._rows(c, k) for k in KINDS}

    def load(self, data: dict[str, list[dict]], by: str = "operator") -> None:
        """Replace whole lists, in one transaction; each changed entry is recorded as a `load`."""
        with self.db.engine.begin() as c:
            for kind, entries in data.items():
                t = self._table(kind)
                before = {e["id"]: e for e in self._rows(c, kind)}
                c.execute(delete(t))
                c.execute(delete(self.db.edges).where(self.db.edges.c.src_label == kind))
                for e in entries:
                    self._write(c, kind, t, e)
                    if self.changes is not None and before.get(e["id"]) != e:
                        self.changes.append_in(c, change_record(kind, e, before.get(e["id"]), "load", by, None))

    def history(self, kind: str | None = None, id: str | None = None, limit: int = 50) -> list[dict]:
        """Recorded writes, newest first; empty when this store keeps no change log."""
        if self.changes is None:
            return []
        where = {k: v for k, v in (("list", kind), ("id", id)) if v}
        return self.changes.query(where=where, limit=limit)

    def export_jsonl(self, directory: Path) -> dict[str, int]:
        """Write each list as `<kind>.jsonl`, one canonical entry per line, sorted by id: the format a
        published map is mounted from."""
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        out = {}
        for kind, rows in self.dump().items():
            (d / f"{kind}.jsonl").write_text("".join(canonical(r) + "\n" for r in rows))
            out[kind] = len(rows)
        return out

    # --- the catalog mirror
    def sync_catalog(self, catalog: dict) -> int:
        """Mirror catalogs.yaml into the catalog table when it changed. Returns rows written (0 if unchanged)."""
        digest = hashlib.sha256(canonical(catalog).encode()).hexdigest()
        m, cat = self.db.meta, self.db.catalog
        with self.db.engine.begin() as c:
            if c.execute(select(m.c.value).where(m.c.key == "catalog")).scalar() == digest:
                return 0
            c.execute(delete(cat))
            seen, n = set(), 0
            for section, entries in (catalog or {}).items():
                for e in entries if isinstance(entries, list) else []:
                    if isinstance(e, dict) and e.get("name") and (section, e["name"]) not in seen:
                        seen.add((section, e["name"]))
                        c.execute(cat.insert().values(section=str(section), name=str(e["name"]), data=e))
                        n += 1
            c.execute(self.db.upsert(m, {"key": "catalog", "value": digest}, ["key"]))
        return n

    def catalog_rows(self, section: str | None = None) -> list[dict]:
        cat = self.db.catalog
        q = select(cat.c.data).order_by(cat.c.section, cat.c.name)
        with self.db.engine.connect() as c:
            return list(c.execute(q.where(cat.c.section == section) if section else q).scalars())

    # --- graph extensions
    def pggraph_sql(self, graph: str = "morphogen") -> list[str]:
        """SQL that registers this map with pgGraph (the `graph` extension, evokoa/pggraph), per its API
        reference: each list's table as a node table keyed by `id`, and `edges` as an edge table once per
        target list, labelled by the reference field (rows whose target is in another list are left out).

        Postgres only. Written against pgGraph 1.2's documented API and not run against the extension here.
        Run the statements, then build the graph and enable sync as its docs describe. pgGraph resolves an
        edge-table row's source by a unique match across the registered node tables, so ids must be unique
        across lists; Morphogen's id prefixes (`type/`, `comp/`, `src/`) keep them so, but the store does
        not enforce it.
        """
        if self.db.dialect != "postgresql":
            raise RuntimeError("pgGraph is a Postgres extension; use the postgres backend")
        s = self.db.schema
        stmts = [f"SELECT graph.add_table('{s}.{k}', 'id')" for k in KINDS]
        for t in KINDS:
            stmts.append(f"SELECT graph.add_edge('{s}.edges', 'src_id', '{s}.{t}', 'dst_id', 'ref', "
                         f"true, NULL, 'field')")
        return stmts


def evidence_log(db: Database) -> Log:
    """Claims with their support. Only the judge writes `measured` evidence (enforced by the tools)."""
    return Log(db, "evidence", check_evidence)
