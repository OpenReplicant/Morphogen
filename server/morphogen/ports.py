"""Ports: what each data feature needs, independent of the backend.

Each port is the interface of a slot in the self-map: ListStore for
`knowledge/lists`, Log for each of `knowledge/logs` (evidence, changes,
journal). `knowledge/indices` has no port yet; its filler today is a scan
inside the queries. A filler implements the port
and declares capability flags, so callers know which guarantees are real.
store.py fills them all; every filler must pass the conformance tests
(ConformanceCases in tests/test_morphogen.py).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

KINDS = ("systems", "slots", "types", "sources", "components")
TRUST = ("measured", "simulated", "stated", "inferred", "asserted")
INTERFACES = ("direct", "simulated")
# Fields that hold references to other entries, by list.
REF_FIELDS = {"systems": ("slots",), "slots": ("system", "accepts", "filled_by"),
              "components": ("type", "source", "system"), "types": (), "sources": ()}
# Capability names are plain strings, compared exactly: a slot's `requires`, a component's `provides`.
# Suggested vocabulary (extend freely): exact, lexical, semantic, graph, temporal, concurrent-writers,
# enforced-append-only, tamper-evident.


@runtime_checkable
class ListStore(Protocol):
    """The lists slot: entries by id in the five lists. Every write is recorded in the changes log."""
    capabilities: dict[str, bool]

    def get(self, kind: str, id: str) -> dict | None: ...
    def put(self, kind: str, entry: dict, by: str = "agent", reason: str | None = None) -> dict: ...
    def query(self, kind: str, where: dict[str, Any] | None = None) -> list[dict]: ...
    def follow(self, kind: str, id: str, field: str, hops: int = 1) -> list[dict]: ...
    def dump(self) -> dict[str, list[dict]]: ...
    def load(self, data: dict[str, list[dict]], by: str = "operator") -> None: ...
    def history(self, kind: str | None = None, id: str | None = None, limit: int = 50) -> list[dict]: ...


@runtime_checkable
class Log(Protocol):
    """One of the logs (evidence, changes, journal): append-only and hash-chained."""
    capabilities: dict[str, bool]

    def append(self, record: dict) -> dict: ...
    def query(self, contains: str | None = None, by: str | None = None, limit: int = 20,
              where: dict[str, Any] | None = None) -> list[dict]: ...
    def verify(self) -> tuple[bool, int | None]: ...
    def dump(self) -> list[dict]: ...
