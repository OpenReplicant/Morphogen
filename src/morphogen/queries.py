"""Read-only queries over the map: drift, blast radius, map-quality metrics.

Used by the MCP server, watchers and the report CLI. Nothing here writes.
Blueprint (hypothetical) and intent (intended) claims are "expected"; drift
compares them with observed claims by slot name, since ports are not visible
in traces.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from statistics import median

from morphogen.domain.ontology import Coupling, Slot, now
from morphogen.store import MapStore, Query

EXPECTED = ("hypothetical", "intended")


def _claims(store: MapStore, kind: str, environment: str, at: datetime | None):
    return store.query(Query(kind=kind, environment=environment, valid_at=at))


def summarize(c) -> dict:
    d = c.model_dump(mode="json")
    d["kind"] = c.kind
    return d


def slots(store: MapStore, environment: str = "sandbox", status: str | None = None,
          at: datetime | None = None) -> list[dict]:
    return [summarize(s) for s in _claims(store, "Slot", environment, at)
            if status is None or s.status == status]


def couplings(store: MapStore, environment: str = "sandbox", slot: str | None = None,
              at: datetime | None = None) -> list[dict]:
    return [summarize(c) for c in _claims(store, "Coupling", environment, at)
            if slot is None or slot in (c.source_slot, c.target_slot)]


def drift(store: MapStore, environment: str = "sandbox", at: datetime | None = None) -> dict:
    """Expected-not-observed and observed-not-expected slots and couplings at valid time `at`."""
    all_slots: list[Slot] = _claims(store, "Slot", environment, at)
    all_couplings: list[Coupling] = _claims(store, "Coupling", environment, at)
    obs_names = {s.name for s in all_slots if s.status == "observed"}
    exp_names = {s.name for s in all_slots if s.status in EXPECTED}
    obs_pairs = {(c.source_slot, c.target_slot) for c in all_couplings if c.status == "observed"}
    exp_pairs = {(c.source_slot, c.target_slot) for c in all_couplings if c.status in EXPECTED}

    def item(c, what: str) -> dict:
        d = {"key": c.key, "kind": c.kind, "status": c.status, "what": what}
        if isinstance(c, Coupling):
            d.update(source_slot=c.source_slot, target_slot=c.target_slot)
        else:
            d.update(name=c.name)
        return d

    return {
        "environment": environment,
        "intended_not_observed": sorted(
            [item(s, "slot") for s in all_slots if s.status in EXPECTED and s.name not in obs_names]
            + [item(c, "coupling") for c in all_couplings
               if c.status in EXPECTED and (c.source_slot, c.target_slot) not in obs_pairs],
            key=lambda d: d["key"]),
        "observed_not_intended": sorted(
            [item(s, "slot") for s in all_slots if s.status == "observed" and s.name not in exp_names]
            + [item(c, "coupling") for c in all_couplings
               if c.status == "observed" and (c.source_slot, c.target_slot) not in exp_pairs],
            key=lambda d: d["key"]),
    }


def blast_radius(store: MapStore, slot_names: list[str], environment: str = "sandbox",
                 at: datetime | None = None) -> dict:
    """Slots reachable from the given slots through couplings of any status, either direction."""
    adj: dict[str, set[str]] = defaultdict(set)
    for c in _claims(store, "Coupling", environment, at):
        adj[c.source_slot].add(c.target_slot)
        adj[c.target_slot].add(c.source_slot)
    depth = {n: 0 for n in slot_names}
    todo = deque(slot_names)
    while todo:
        n = todo.popleft()
        for m in adj[n]:
            if m not in depth:
                depth[m] = depth[n] + 1
                todo.append(m)
    affected = sorted((n for n in depth if n not in slot_names), key=lambda n: (depth[n], n))
    return {"from": slot_names, "affected": [{"slot": n, "depth": depth[n]} for n in affected]}


def metrics(store: MapStore, environment: str = "sandbox", at: datetime | None = None) -> dict:
    """Map quality for one environment: coverage, precision, freshness, drift."""
    t = at or now()
    cs: list[Coupling] = _claims(store, "Coupling", environment, at)
    obs = [c for c in cs if c.status == "observed"]
    obs_pairs = {(c.source_slot, c.target_slot) for c in obs}
    exp_pairs = {(c.source_slot, c.target_slot) for c in cs if c.status in EXPECTED}
    seen = store.last_seen([c.key for c in obs])
    ages = [(t - s).total_seconds() for s in seen.values()]
    d = drift(store, environment, at)
    return {
        "environment": environment,
        "expected_couplings": len(exp_pairs),
        "observed_couplings": len(obs_pairs),
        "coverage": round(len(exp_pairs & obs_pairs) / len(exp_pairs), 3) if exp_pairs else None,
        "precision": round(len(exp_pairs & obs_pairs) / len(obs_pairs), 3) if obs_pairs else None,
        "freshness_s": {"median": round(median(ages), 1), "max": round(max(ages), 1)} if ages else None,
        "drift": {k: len(d[k]) for k in ("intended_not_observed", "observed_not_intended")},
    }
