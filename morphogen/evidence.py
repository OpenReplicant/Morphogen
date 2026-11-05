"""Evidence: an append-only, hash-chained log of claims with their support, in SQLite.

Each record carries the hash of the one before it, so an edit shows up in `verify`. SQLite triggers
refuse UPDATE and DELETE; whoever can write the file can drop them, and the chain then shows the
edit. The file lives in git's own directory (`<git common dir>/morphogen/evidence.db`), so candidate
commits cannot sweep it up, branch switches cannot lose it, and every worktree shares it.

Trust: measured (the judge, on the real system), simulated (the judge, on a model), stated (from a
source), inferred (reasoned), asserted (the operator's say-so). Only the judge writes measured or
simulated records.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

TRUST = ("measured", "simulated", "stated", "inferred", "asserted")
GENESIS = "0" * 64


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def record_hash(record: dict) -> str:
    return hashlib.sha256(canonical({k: v for k, v in record.items() if k != "hash"}).encode()).hexdigest()


def default_path(root: Path) -> Path:
    common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=root, capture_output=True,
                            text=True, check=True).stdout.strip()
    d = (Path(root) / common).resolve() / "morphogen"
    d.mkdir(parents=True, exist_ok=True)
    return d / "evidence.db"


class Evidence:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as c:
            c.execute("CREATE TABLE IF NOT EXISTS evidence (seq INTEGER PRIMARY KEY, hash TEXT NOT NULL, "
                      "prev TEXT NOT NULL, raw TEXT NOT NULL)")
            for op in ("UPDATE", "DELETE"):
                c.execute(f"CREATE TRIGGER IF NOT EXISTS evidence_no_{op.lower()} BEFORE {op} ON evidence "
                          "BEGIN SELECT RAISE(ABORT, 'evidence is append-only'); END")

    @classmethod
    def for_project(cls, root: Path) -> Evidence:
        return cls(default_path(root))

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def append(self, record: dict) -> dict:
        if not isinstance(record, dict):
            raise ValueError("a record is a mapping")
        if record.get("trust") not in TRUST:
            raise ValueError(f"trust must be one of {', '.join(TRUST)}")
        if not record.get("claim") or not record.get("by"):
            raise ValueError("a record needs 'claim' and 'by'")
        c = self._connect()
        try:
            c.execute("BEGIN IMMEDIATE")  # take the write lock first: two writers cannot fork the chain
            last = c.execute("SELECT seq, hash FROM evidence ORDER BY seq DESC LIMIT 1").fetchone()
            rec = dict(record)
            rec["seq"] = last[0] + 1 if last else 1
            rec["at"] = rec.get("at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            rec["prev"] = last[1] if last else GENESIS
            rec.pop("hash", None)
            rec["hash"] = record_hash(rec)
            c.execute("INSERT INTO evidence (seq, hash, prev, raw) VALUES (?, ?, ?, ?)",
                      (rec["seq"], rec["hash"], rec["prev"], canonical(rec)))
            c.execute("COMMIT")
            return rec
        except BaseException:
            c.execute("ROLLBACK")
            raise
        finally:
            c.close()

    def dump(self) -> list[dict]:
        c = self._connect()
        try:
            return [json.loads(r) for (r,) in c.execute("SELECT raw FROM evidence ORDER BY seq")]
        finally:
            c.close()

    def verify(self) -> tuple[bool, int | None]:
        prev = GENESIS
        for i, rec in enumerate(self.dump(), start=1):
            if rec.get("prev") != prev or rec.get("seq") != i or record_hash(rec) != rec.get("hash"):
                return False, i
            prev = rec["hash"]
        return True, None

    def query(self, contains: str | None = None, by: str | None = None, limit: int = 20,
              where: dict[str, Any] | None = None) -> list[dict]:
        """Newest first."""
        out = []
        for rec in reversed(self.dump()):
            if by and rec.get("by") != by:
                continue
            if contains and contains.lower() not in canonical(rec).lower():
                continue
            if where and any(rec.get(k) != v for k, v in where.items()):
                continue
            out.append(rec)
            if len(out) >= limit:
                break
        return out
