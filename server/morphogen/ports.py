"""Ports: what each data feature needs, independent of the backend.

A backend implements a port and declares capability flags, so callers know
which guarantees are real instead of assuming the strongest backend.
Every backend must pass the same conformance tests (the Conformance class in tests/test_morphogen.py).
"""

from __future__ import annotations

from typing import Any, Protocol

KINDS = ("systems", "slots", "types", "sources", "components")
TRUST = ("measured", "simulated", "stated", "inferred", "asserted")
INTERFACES = ("direct", "simulated")


class ListStore(Protocol):
    capabilities: dict[str, bool]

    def get(self, kind: str, id: str) -> dict | None: ...
    def put(self, kind: str, entry: dict) -> dict: ...
    def query(self, kind: str, where: dict[str, Any] | None = None) -> list[dict]: ...
    def follow(self, kind: str, id: str, field: str, hops: int = 1) -> list[dict]: ...
    def dump(self) -> dict[str, list[dict]]: ...
    def load(self, data: dict[str, list[dict]]) -> None: ...


class EvidenceLog(Protocol):
    capabilities: dict[str, bool]

    def append(self, record: dict) -> dict: ...
    def query(self, contains: str | None = None, by: str | None = None, limit: int = 20) -> list[dict]: ...
    def verify(self) -> tuple[bool, int | None]: ...
    def dump(self) -> list[dict]: ...
