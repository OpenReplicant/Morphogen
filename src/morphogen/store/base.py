"""Bitemporal claim store interface and the write rules shared by providers.

A claim's identity is (key, status, environment). Rows are never overwritten:
a change closes the current version's valid interval and opens a new one, and
the closed version is itself a new row (decision 0007). A row leaves the
record when `record_to` is set, so "as recorded at R" queries see what the
system believed then.

Write methods are for ingestors only (invariant 1). Readers get a store
opened with a read-only role.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from morphogen.domain.ontology import CLAIM_FIELDS, Claim, from_row, now

Identity = tuple[str, str, str]  # key, status, environment


@dataclass
class Ids:
    nodes: list[str] = field(default_factory=list)
    edges: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"nodes": self.nodes, "edges": self.edges}


@dataclass
class ChangeSet:
    created: Ids = field(default_factory=Ids)
    changed: Ids = field(default_factory=Ids)
    retired: Ids = field(default_factory=Ids)
    labels: set[str] = field(default_factory=set)

    def merge(self, other: ChangeSet) -> ChangeSet:
        for name in ("created", "changed", "retired"):
            mine, theirs = getattr(self, name), getattr(other, name)
            mine.nodes += theirs.nodes
            mine.edges += theirs.edges
        self.labels |= other.labels
        return self

    @property
    def empty(self) -> bool:
        return not any(
            getattr(self, n).nodes or getattr(self, n).edges for n in ("created", "changed", "retired")
        )


@dataclass
class Query:
    kind: str | None = None
    status: str | None = None
    environment: str | None = None
    key_prefix: str | None = None
    valid_at: datetime | None = None  # default: now
    recorded_at: datetime | None = None  # default: now (latest knowledge)
    include_retracted: bool = False


def edge_ids(claim: Claim) -> list[str]:
    return [f"{claim.key}|{rel}|{target}" for rel, target in claim.refs()]


def identity(claim: Claim) -> Identity:
    return (claim.key, claim.status, claim.environment)


def to_row(claim: Claim) -> dict:
    data = claim.model_dump(mode="python", include=set(CLAIM_FIELDS))
    return {"id": str(uuid.uuid4()), "kind": claim.kind, "record_to": None,
            "content": claim.content(), **data}


def row_to_claim(row: dict) -> Claim:
    fields = {k: row[k] for k in CLAIM_FIELDS}
    return from_row(row["kind"], {**row["content"], **fields})


class MapStore(ABC):
    """Swappable provider for the map (invariant 6)."""

    # -- primitives each provider implements --------------------------------

    @abstractmethod
    def _open_row(self, ident: Identity) -> dict | None:
        """The current open (valid_to null, record_to null) row for an identity."""

    @abstractmethod
    def _insert(self, rows: list[dict]) -> None: ...

    @abstractmethod
    def _close_record(self, row_ids: list[str], at: datetime) -> None:
        """Set record_to on rows; nothing else ever changes on a stored row."""

    @abstractmethod
    def _select(self, q: Query) -> list[dict]: ...

    @abstractmethod
    def _history(self, key: str) -> list[dict]: ...

    @abstractmethod
    def touch(self, keys: Iterable[str], at: datetime) -> None:
        """Record that observed claims were seen again (freshness); not a claim change."""

    @abstractmethod
    def last_seen(self, keys: Iterable[str]) -> dict[str, datetime]: ...

    def transaction(self):
        """Context manager grouping writes; providers without transactions use a no-op."""
        from contextlib import nullcontext

        return nullcontext()

    # -- write side (ingestors only) -----------------------------------------

    def upsert(self, claims: Iterable[Claim]) -> ChangeSet:
        """Open, keep or change claims. Same content: no-op. Different: close and reopen."""
        cs = ChangeSet()
        recorded = now()
        with self.transaction():
            for claim in claims:
                cs.labels.add(claim.kind)
                current = self._open_row(identity(claim))
                if current is None:
                    self._insert([to_row(claim)])
                    cs.created.nodes.append(claim.key)
                    cs.created.edges += edge_ids(claim)
                    continue
                old = row_to_claim(current)
                if old.content() == claim.content() and old.confidence == claim.confidence \
                        and old.retracted == claim.retracted:
                    continue
                at = max(claim.valid_from, old.valid_from)
                closed = to_row(old.model_copy(update={"valid_to": at, "recorded_at": recorded}))
                opened = to_row(claim.model_copy(update={"valid_from": at, "recorded_at": recorded}))
                self._close_record([current["id"]], recorded)
                self._insert([closed, opened])
                cs.changed.nodes.append(claim.key)
                before, after = set(edge_ids(old)), set(edge_ids(claim))
                cs.created.edges += sorted(after - before)
                cs.retired.edges += sorted(before - after)
        return cs

    def retire(self, idents: Iterable[Identity], at: datetime) -> ChangeSet:
        """Close valid intervals at `at`. History stays; current views exclude them."""
        cs = ChangeSet()
        recorded = now()
        with self.transaction():
            for ident in idents:
                current = self._open_row(ident)
                if current is None:
                    continue
                old = row_to_claim(current)
                cs.labels.add(old.kind)
                closed = to_row(old.model_copy(update={"valid_to": max(at, old.valid_from),
                                                       "recorded_at": recorded}))
                self._close_record([current["id"]], recorded)
                self._insert([closed])
                cs.retired.nodes.append(old.key)
                cs.retired.edges += edge_ids(old)
        return cs

    # -- read side ------------------------------------------------------------

    def query(self, q: Query | None = None, **kw) -> list[Claim]:
        q = q or Query(**kw)
        return [row_to_claim(r) for r in self._select(q)]

    def history(self, key: str) -> list[Claim]:
        return [row_to_claim(r) for r in self._history(key)]


def visible(row: dict, q: Query) -> bool:
    """The bitemporal and filter predicate, shared by in-process providers."""
    t, r = q.valid_at or now(), q.recorded_at or now()
    return (
        (q.kind is None or row["kind"] == q.kind)
        and (q.status is None or row["status"] == q.status)
        and (q.environment is None or row["environment"] == q.environment)
        and (q.key_prefix is None or row["key"].startswith(q.key_prefix))
        and row["valid_from"] <= t and (row["valid_to"] is None or row["valid_to"] > t)
        and row["recorded_at"] <= r and (row["record_to"] is None or row["record_to"] > r)
        and (q.include_retracted or not row["retracted"])
    )
