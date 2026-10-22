"""Drift watcher: event-driven (on completions touching slots or couplings) and as a sweep.

Emits finding.created whenever the drift for an environment changes, with
`causationid` set to the event that triggered the check. Read-only on the map.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from morphogen import queries
from morphogen.events import make
from morphogen.store import MapStore

log = logging.getLogger(__name__)
SLOT = "drift-watcher"
GATE = {"Slot", "Coupling"}


class DriftWatcher:
    def __init__(self, store: MapStore, publish: Callable[[dict], str], target: str,
                 environments: tuple[str, ...] = ("sandbox",)) -> None:
        self.store = store
        self.publish = publish
        self.target = target
        self.environments = environments
        self.last: dict[str, frozenset] = {}
        self._lock = threading.Lock()

    def on_completion(self, event: dict) -> None:
        """Cheap match on labels first; query only when slots or couplings changed."""
        data = event["data"]
        if data.get("status") != "succeeded" or not GATE & set(data.get("labels", [])):
            return
        if not any(data[k]["nodes"] for k in ("created", "changed", "retired")):
            return
        self.check(event.get("environment", "sandbox"), causation=event["id"])

    def sweep(self) -> list[dict]:
        return [f for env in self.environments if (f := self.check(env)) is not None]

    def check(self, environment: str, causation: str | None = None) -> dict | None:
        with self._lock:
            d = queries.drift(self.store, environment)
            sig = frozenset(i["key"] for k in ("intended_not_observed", "observed_not_intended")
                            for i in d[k])
            if self.last.get(environment) == sig:
                return None
            self.last[environment] = sig
        missing, unexpected = d["intended_not_observed"], d["observed_not_intended"]
        severity = "info" if not sig else "warning"
        finding = make("finding.created", f"watcher:{SLOT}", {
            "target": self.target,
            "kind": "drift",
            "summary": (f"drift in {environment}: {len(missing)} expected not observed, "
                        f"{len(unexpected)} observed not expected") if sig
                       else f"no drift in {environment}",
            "severity": severity,
            "evidence": sorted(sig),
            "details": d,
        }, environment=environment, causationid=causation)
        self.publish(finding)
        return finding


def run_sweeps(watcher: DriftWatcher, interval_s: float, stop: threading.Event) -> None:
    while not stop.wait(interval_s):
        try:
            watcher.sweep()
        except Exception:
            log.exception("drift sweep failed")
