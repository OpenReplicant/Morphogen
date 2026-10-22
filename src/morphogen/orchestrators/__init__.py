"""Orchestrator adapters: the only code that touches the world (invariant 2).

An adapter watches one environment's folder under `intent/` and reconciles it.
It never reads the map (invariant 7); what happened is learned only from the
traces the reconciled services emit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Result:
    environment: str
    revision: str  # content revision of the environment folder that was applied
    commands: list[list[str]] = field(default_factory=list)
    ok: bool = True
    output: str = ""
    skipped: str | None = None  # why nothing ran


class Orchestrator(Protocol):
    environment: str

    def revision(self) -> str: ...

    def reconcile(self) -> Result: ...
