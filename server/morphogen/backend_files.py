"""Files backend: one JSONL file per list, and an append-only, hash-chained evidence log.

The files are the canonical dump format, so migrating to another backend is
dump then load.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .ports import KINDS, TRUST


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _matches(entry: dict, where: dict[str, Any]) -> bool:
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


class FilesListStore:
    capabilities = {"concurrent_writers": False, "native_multi_hop": False, "vector_search": False}

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, kind: str) -> Path:
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}; expected one of {', '.join(KINDS)}")
        return self.dir / f"{kind}.jsonl"

    def _read(self, kind: str) -> dict[str, dict]:
        p = self._path(kind)
        if not p.exists():
            return {}
        out = {}
        for line in p.read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                out[e["id"]] = e
        return out

    def _write(self, kind: str, entries: dict[str, dict]) -> None:
        lines = [canonical(entries[k]) for k in sorted(entries)]
        tmp = self._path(kind).with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + ("\n" if lines else ""))
        tmp.replace(self._path(kind))

    def get(self, kind: str, id: str) -> dict | None:
        return self._read(kind).get(id)

    def put(self, kind: str, entry: dict) -> dict:
        if not isinstance(entry, dict) or not entry.get("id"):
            raise ValueError("an entry needs a non-empty 'id'")
        entries = self._read(kind)
        entries[entry["id"]] = entry
        self._write(kind, entries)
        return entry

    def query(self, kind: str, where: dict[str, Any] | None = None) -> list[dict]:
        entries = self._read(kind).values()
        return [e for e in entries if _matches(e, where or {})]

    def follow(self, kind: str, id: str, field: str, hops: int = 1) -> list[dict]:
        """Entries reachable from `id` by following reference `field`, up to `hops` steps.

        References are ids, in any list. Returns each reached entry once.
        """
        index = {e["id"]: e for k in KINDS for e in self._read(k).values()}
        start = index.get(id) or self.get(kind, id)
        if start is None:
            return []
        seen, frontier, out = {id}, [start], []
        for _ in range(max(hops, 0)):
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
        return {k: [self._read(k)[i] for i in sorted(self._read(k))] for k in KINDS}

    def load(self, data: dict[str, list[dict]]) -> None:
        for kind, entries in data.items():
            self._write(kind, {e["id"]: e for e in entries})


class FilesEvidenceLog:
    """Append-only JSONL; each record carries the hash of the one before it."""

    capabilities = {"enforced_append_only": False, "tamper_evident": True}
    GENESIS = "0" * 64

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _records(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]

    @staticmethod
    def _hash(record: dict) -> str:
        body = {k: v for k, v in record.items() if k != "hash"}
        return hashlib.sha256(canonical(body).encode()).hexdigest()

    def append(self, record: dict) -> dict:
        if record.get("trust") not in TRUST:
            raise ValueError(f"trust must be one of {', '.join(TRUST)}")
        if not record.get("claim") or not record.get("by"):
            raise ValueError("evidence needs 'claim' and 'by'")
        records = self._records()
        rec = dict(record)
        rec["seq"] = len(records) + 1
        rec["at"] = rec.get("at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rec["prev"] = records[-1]["hash"] if records else self.GENESIS
        rec.pop("hash", None)
        rec["hash"] = self._hash(rec)
        with self.path.open("a") as f:
            f.write(canonical(rec) + "\n")
        return rec

    def verify(self) -> tuple[bool, int | None]:
        prev = self.GENESIS
        for i, rec in enumerate(self._records(), start=1):
            if rec.get("prev") != prev or rec.get("seq") != i or self._hash(rec) != rec.get("hash"):
                return False, i
            prev = rec["hash"]
        return True, None

    def query(self, contains: str | None = None, by: str | None = None, limit: int = 20) -> list[dict]:
        out = []
        for rec in reversed(self._records()):
            if by and rec.get("by") != by:
                continue
            if contains and contains.lower() not in canonical(rec).lower():
                continue
            out.append(rec)
            if len(out) >= limit:
                break
        return out

    def dump(self) -> list[dict]:
        return self._records()
