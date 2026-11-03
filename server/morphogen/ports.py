"""Ports: what each data feature needs, independent of the backend.

Each port is the interface of a slot in the self-map: ListStore for
`knowledge/lists`, Log for each of `knowledge/logs` (evidence, journal). `knowledge/indices` has no port yet; its filler today is a scan
inside the queries. A filler implements the port
and declares capability flags, so callers know which guarantees are real.
store.py fills them all; every filler must pass the conformance tests
(ConformanceCases in tests/test_morphogen.py).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

KINDS = ("systems", "slots", "types", "sources", "components", "parameters")
TRUST = ("measured", "simulated", "stated", "inferred", "asserted")
INTERFACES = ("direct", "simulated")
# Fields that hold references to other entries, by list.
REF_FIELDS = {"systems": ("slots",), "slots": ("system", "accepts", "filled_by"),
              "components": ("type", "source", "system"), "types": (), "sources": (), "parameters": ("of",)}
# Relations beyond the fields above: any entry may carry `links`, a mapping from a relation name (free
# text, like capability names: writes, reads, triggers, next, realizes, ...) to an id or a list of ids.
# They are references like the fields above: checked for dangling ids, walked by follow, qualified across
# maps.
LINKS = "links"
# Who may change a parameter: the agent (a strategy may tune it), the operator (by hand, with review) or
# the judge (part of the rules a candidate is scored by).
OWNERS = ("agent", "operator", "judge")
# Capability names are plain strings, compared exactly: a slot's `requires`, a component's `provides`.
# Suggested vocabulary (extend freely): exact, lexical, semantic, graph, temporal, concurrent-writers,
# enforced-append-only, tamper-evident.


@runtime_checkable
class ListStore(Protocol):
    """The lists slot: entries by id in the five lists."""
    capabilities: dict[str, bool]

    def get(self, kind: str, id: str) -> dict | None: ...
    def put(self, kind: str, entry: dict) -> dict: ...
    def query(self, kind: str, where: dict[str, Any] | None = None) -> list[dict]: ...
    def follow(self, kind: str, id: str, field: str, hops: int = 1) -> list[dict]: ...
    def dump(self) -> dict[str, list[dict]]: ...
    def load(self, data: dict[str, list[dict]]) -> None: ...


@runtime_checkable
class Log(Protocol):
    """One of the logs (evidence, journal): append-only and hash-chained."""
    capabilities: dict[str, bool]

    def append(self, record: dict) -> dict: ...
    def query(self, contains: str | None = None, by: str | None = None, limit: int = 20,
              where: dict[str, Any] | None = None) -> list[dict]: ...
    def verify(self) -> tuple[bool, int | None]: ...
    def dump(self) -> list[dict]: ...
