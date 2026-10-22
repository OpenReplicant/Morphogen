"""Blueprint ingestor: blueprint.submitted -> hypothetical slots, ports, couplings.

Resubmitting a blueprint replaces it: claims from the previous submission that
are missing from the new one are retired.
"""

from __future__ import annotations

from morphogen.domain.ontology import (
    Claim,
    Coupling,
    CouplingType,
    Level,
    Port,
    Provenance,
    Slot,
    Status,
    now,
)
from morphogen.events import parse_time
from morphogen.store import ChangeSet, MapStore


def to_datapoints(event: dict) -> list[Claim]:
    """Pure mapping, unit-testable without storage."""
    data = event["data"]
    common = dict(
        status=Status.HYPOTHETICAL,
        level=Level.INSTANCE,
        environment=event.get("environment", "sandbox"),
        provenance=Provenance.ASSERTED,
        confidence=0.3,
        source_event_id=event["id"],
        valid_from=parse_time(event.get("validtime", event["time"])),
        recorded_at=now(),
    )
    bp = data["blueprint_id"]
    names = {s["id"]: s.get("service", s["id"]) for s in data["slots"]}
    ports: dict[str, Port] = {}
    claims: list[Claim] = []
    for s in data["slots"]:
        slot_key = f"{bp}/{s['id']}"
        claims.append(Slot(
            key=slot_key, role=s["role"], name=names[s["id"]],
            cardinality=s.get("cardinality", "exclusive"), scope=s.get("scope"),
            parent=f"{bp}/{s['parent']}" if s.get("parent") else None,
            requirements=s.get("requirements", []), provider_hint=s.get("provider_hint"),
            **common,
        ))
        for p in s.get("ports", []):
            port = Port(key=f"{slot_key}.{p['name']}", slot=slot_key, name=p["name"],
                        direction=p["direction"], contract=p.get("contract"), **common)
            ports[f"{s['id']}.{p['name']}"] = port
            claims.append(port)

    for c in data["couplings"]:
        src, dst = ports[c["from"]], ports[c["to"]]
        claims.append(Coupling(
            key=f"{bp}/{c['id']}",
            coupling_type=CouplingType(c["type"]),
            source_port=src.key, target_port=dst.key,
            source_slot=names[c["from"].split(".", 1)[0]],
            target_slot=names[c["to"].split(".", 1)[0]],
            contract=c.get("contract"),
            **common,
        ))
    return claims


def check(event: dict) -> list[str]:
    """Structural errors JSON Schema cannot express: dangling slot.port references."""
    data = event["data"]
    ids = {s["id"] for s in data["slots"]}
    known = {f"{s['id']}.{p['name']}" for s in data["slots"] for p in s.get("ports", [])}
    errors = [f"coupling {c['id']}: unknown port {c[end]!r}"
              for c in data["couplings"] for end in ("from", "to") if c[end] not in known]
    errors += [f"slot {s['id']}: unknown parent {s['parent']!r}"
               for s in data["slots"] if s.get("parent") and s["parent"] not in ids]
    return errors


class BlueprintIngestor:
    pipeline = "blueprint"
    types = ("blueprint.submitted",)

    def run(self, event: dict, store: MapStore) -> ChangeSet:
        claims = to_datapoints(event)
        bp = event["data"]["blueprint_id"]
        env = event.get("environment", "sandbox")
        with store.transaction():
            cs = store.upsert(claims)
            keep = {c.key for c in claims}
            stale = [(c.key, c.status, c.environment)
                     for c in store.query(status="hypothetical", environment=env, key_prefix=f"{bp}/")
                     if c.key not in keep]
            cs.merge(store.retire(stale, parse_time(event.get("validtime", event["time"]))))
        return cs
