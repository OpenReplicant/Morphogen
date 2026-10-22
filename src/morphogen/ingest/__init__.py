"""Ingestors: the only writers of the map (invariant 1).

Each ingestor maps one kind of input to claims and writes them through the map
store. The router runs it and publishes a completion event (decision 0006).
"""

from __future__ import annotations

from typing import Protocol

from morphogen.store import ChangeSet, MapStore


class Ingestor(Protocol):
    pipeline: str
    types: tuple[str, ...]  # short CloudEvent types this ingestor handles

    def run(self, event: dict, store: MapStore) -> ChangeSet: ...
