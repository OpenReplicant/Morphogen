"""The resolver interface, and what every backend shares: records, entities, blocking, merge and split.

A backend only supplies `score(a_tokens, b_tokens)` in [0, 1]; everything else is here, so swapping
backends changes how pairs are scored and nothing else.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Protocol

from . import settings
from .text import codes_conflict, tokens, words_conflict


class Resolver(Protocol):
    def add(self, record: dict) -> str: ...
    def match(self, a: dict, b: dict) -> float: ...
    def resolve(self, record: dict) -> list[tuple[str, float]]: ...
    def merge(self, a: str, b: str) -> str: ...
    def split(self, entity: str, records: list[str]) -> str: ...
    def entity_of(self, record_id: str) -> str: ...


class Base:
    """Known records indexed by token; entities as groups of record ids."""

    def __init__(self):
        self.records: dict[str, dict] = {}
        self.toks: dict[str, list[str]] = {}
        self.index: dict[str, set[str]] = defaultdict(set)
        self.entity: dict[str, str] = {}
        self.members: dict[str, set[str]] = defaultdict(set)
        self._next = 0

    # --- what a backend provides

    def score(self, a: list[str], b: list[str]) -> float:
        raise NotImplementedError

    def changed(self) -> None:
        """Called after records are added (a backend may refresh statistics)."""

    # --- the interface

    def pair(self, ta: list[str], tb: list[str]) -> float:
        """The backend's score, lowered when the names disagree on a model code or on distinctive words."""
        s = self.score(ta, tb)
        if codes_conflict(ta, tb):
            s *= settings.MODEL_MISMATCH
        if words_conflict(ta, tb):
            s *= settings.WORD_MISMATCH
        return max(0.0, min(1.0, s))

    def match(self, a: dict, b: dict) -> float:
        return self.pair(tokens(a), tokens(b))

    def candidates(self, toks: list[str]) -> list[str]:
        """Blocking: known records sharing at least one token that is not too common."""
        n = max(len(self.records), 1)
        hits: dict[str, int] = defaultdict(int)
        for t in set(toks):
            ids = self.index.get(t, ())
            if ids and len(ids) / n <= settings.BLOCK_MAX_DF:
                for rid in ids:
                    hits[rid] += 1
        ranked = sorted(hits, key=lambda r: (-hits[r], r))
        return ranked[: settings.BLOCK_LIMIT]

    def resolve(self, record: dict) -> list[tuple[str, float]]:
        toks = tokens(record)
        best: dict[str, float] = {}
        for rid in self.candidates(toks):
            if rid == record.get("id"):
                continue
            s = self.pair(toks, self.toks[rid])
            e = self.entity[rid]
            if s >= settings.THRESHOLD and s > best.get(e, -1.0):
                best[e] = s
        return sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))

    def add(self, record: dict) -> str:
        rid = str(record["id"])
        found = self.resolve(record)
        e = found[0][0] if found else self._new_entity()
        self.records[rid] = record
        self.toks[rid] = tokens(record)
        for t in set(self.toks[rid]):
            self.index[t].add(rid)
        self.entity[rid] = e
        self.members[e].add(rid)
        self.changed()
        return e

    def entity_of(self, record_id: str) -> str:
        return self.entity[record_id]

    def merge(self, a: str, b: str) -> str:
        if a == b:
            return a
        for rid in self.members.pop(b, set()):
            self.entity[rid] = a
            self.members[a].add(rid)
        return a

    def split(self, entity: str, records: list[str]) -> str:
        e = self._new_entity()
        for rid in records:
            if self.entity.get(rid) == entity:
                self.members[entity].discard(rid)
                self.entity[rid] = e
                self.members[e].add(rid)
        return e

    def _new_entity(self) -> str:
        self._next += 1
        return f"e{self._next}"
