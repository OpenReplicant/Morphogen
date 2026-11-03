"""The store: the lists and the two logs in one SQL database, through SQLAlchemy Core.

SQLite by default (one file, Python's own driver). Any database SQLAlchemy
supports, by URL and engine options in morphogen.yaml (`database:`); only
SQLite is tested here. The tables:

- one table per list (`systems`, `slots`, `types`, `sources`, `components`),
  each `(id, data)` with `data` as JSON;
- two logs, `evidence` and `journal`, each `(seq, hash, prev, raw, record)`,
  hash-chained.

Two writers cannot fork a chain on any database: `seq` is the primary key, so the second
of two appends with the same number fails and is retried. On SQLite, writes
also take the lock up front (BEGIN IMMEDIATE), and triggers refuse UPDATE and
DELETE on the logs, so append-only is enforced there; elsewhere it is evident
from the chain, not enforced (add your database's own trigger if you need it).

JSONL is the format for publishing a map (`export_jsonl`) and for the seed
lists; mounted maps are read from it (maps.py).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from sqlalchemy import (JSON, BigInteger, Column, MetaData, Table, Text, create_engine, delete, event, select)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateSchema

from .ports import KINDS, TRUST

LOGS = ("evidence", "journal")
GENESIS = "0" * 64
JSONT = JSON()
RETRIES = 8  # appends that lost a race for the next seq


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


# --- the database

def _engine(url: str, options: dict | None = None):
    options = dict(options or {})
    if not url.startswith("sqlite"):
        return create_engine(url, **options)
    options["connect_args"] = {"timeout": 30, **(options.get("connect_args") or {})}
    eng = create_engine(url, **options)

    @event.listens_for(eng, "connect")
    def _connect(dbapi, _):
        dbapi.isolation_level = None  # the driver issues no BEGIN of its own; we do, below
        cur = dbapi.cursor()
        cur.execute("PRAGMA journal_mode=WAL")  # readers do not wait for the writer
        cur.close()

    @event.listens_for(eng, "begin")
    def _begin(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")  # take the write lock up front

    return eng


def retrying(fn):
    """Run a transaction again if another writer took the log's next seq first."""
    for attempt in range(RETRIES):
        try:
            return fn()
        except IntegrityError:
            if attempt == RETRIES - 1:
                raise
            time.sleep(0.01 * (attempt + 1))


class Database:
    """One database: the lists and the two logs.

    `url` is any SQLAlchemy URL; `options` go to `create_engine` (pool settings, `connect_args` for
    the driver's own flags); `schema` puts the tables in a schema on databases that have them."""

    def __init__(self, url: str, schema: str | None = None, options: dict | None = None):
        self.url = url
        self.engine = _engine(url, options)
        self.dialect = self.engine.dialect.name
        self.schema = schema if self.dialect != "sqlite" else None
        md = MetaData(schema=self.schema)
        self.lists = {k: Table(k, md, Column("id", Text, primary_key=True), Column("data", JSONT, nullable=False))
                      for k in KINDS}
        self.logs = {n: Table(n, md, Column("seq", BigInteger, primary_key=True, autoincrement=False),
                              Column("hash", Text, nullable=False), Column("prev", Text, nullable=False),
                              Column("raw", Text, nullable=False), Column("record", JSONT, nullable=False))
                     for n in LOGS}
        if self.schema:
            with self.engine.begin() as c:
                c.execute(CreateSchema(self.schema, if_not_exists=True))
        md.create_all(self.engine)
        self.enforced = self.dialect == "sqlite"
        if self.enforced:
            with self.engine.begin() as c:
                for t in LOGS:
                    for op in ("UPDATE", "DELETE"):
                        c.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS {t}_no_{op.lower()} BEFORE {op} ON {t} "
                                          f"BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END")

    def q(self, name: str) -> str:
        return f"{self.schema}.{name}" if self.schema else name

    def replace(self, c, table: Table, row: dict, keys: list[str]) -> None:
        """Insert or replace one row (portable: delete by key, then insert, in the caller's transaction)."""
        c.execute(delete(table).where(*(table.c[k] == row[k] for k in keys)))
        c.execute(table.insert().values(**row))


# --- the logs

class Log:
    """An append-only, hash-chained log: each record carries the hash of the one before it, and the
    database refuses to change or delete a row. `raw` is the canonical text the hash was computed over,
    so verifying never depends on how the database stores JSON."""

    GENESIS = GENESIS

    def __init__(self, db: Database, name: str, check=check_record):
        self.db, self.name, self.table, self._check = db, name, db.logs[name], check
        self.capabilities = {"enforced_append_only": db.enforced, "tamper_evident": True,
                             "concurrent_writers": True}
        self.path = f"{db.engine.url.render_as_string(hide_password=True)}#{db.q(name)}"

    def _records(self) -> list[dict]:
        with self.db.engine.connect() as c:
            return [json.loads(r) for r in c.execute(select(self.table.c.raw).order_by(self.table.c.seq)).scalars()]

    def append_in(self, c, record: dict) -> dict:
        """Append inside the caller's transaction (a list write and its change record commit together)."""
        self._check(record)
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
        def run():
            with self.db.engine.begin() as c:
                return self.append_in(c, record)
        return retrying(run)

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

    def __init__(self, db: Database):
        self.db = db
        self.capabilities = {"concurrent_writers": True, "database": db.dialect}

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

    def put(self, kind: str, entry: dict) -> dict:
        t = self._table(kind)
        if not isinstance(entry, dict) or not entry.get("id"):
            raise ValueError("an entry needs a non-empty 'id'")
        with self.db.engine.begin() as c:
            self._write(c, kind, t, entry)
        return entry

    def _write(self, c, kind: str, t: Table, entry: dict) -> None:
        id = str(entry["id"])
        self.db.replace(c, t, {"id": id, "data": entry}, ["id"])

    def query(self, kind: str, where: dict[str, Any] | None = None) -> list[dict]:
        with self.db.engine.connect() as c:
            return [e for e in self._rows(c, kind) if matches(e, where or {})]

    def follow(self, kind: str, id: str, field: str, hops: int = 1) -> list[dict]:
        """Entries reachable from `id` along reference `field`, nearest first, each once. References are
        ids in any list; the walk is in Python, since maps are small."""
        index = {e["id"]: e for rows in self.dump().values() for e in rows}
        if id not in index:
            return []
        seen, frontier, out = {id}, [index[id]], []
        for _ in range(max(int(hops), 0)):
            nxt = []
            for e in frontier:
                refs = e.get(field) or []
                for r in refs if isinstance(refs, list) else [refs]:
                    if r in index and r not in seen:
                        seen.add(r)
                        out.append(index[r])
                        nxt.append(index[r])
            frontier = nxt
        return out

    def dump(self) -> dict[str, list[dict]]:
        with self.db.engine.connect() as c:
            return {k: self._rows(c, k) for k in KINDS}

    def load(self, data: dict[str, list[dict]]) -> None:
        """Replace whole lists, in one transaction."""
        with self.db.engine.begin() as c:
            for kind, entries in data.items():
                t = self._table(kind)
                c.execute(delete(t))
                for e in entries:
                    self._write(c, kind, t, e)

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


def evidence_log(db: Database) -> Log:
    """Claims with their support. Only the judge writes `measured` evidence (enforced by the tools)."""
    return Log(db, "evidence", check_evidence)
