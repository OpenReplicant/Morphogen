"""Blueprint ingestor: blueprint.submitted -> hypothetical slots, ports, couplings.

Only ingestors write the map (invariant 1). Ends by publishing a completion
event (decision 0006).
"""

from __future__ import annotations

from datetime import datetime

from morphogen.domain.ontology import (
    Coupling,
    CouplingType,
    Environment,
    Level,
    Port,
    Provenance,
    Slot,
    Status,
    now,
)


def to_datapoints(event: dict) -> list[Slot | Coupling]:
    """Pure mapping, unit-testable without cognee storage."""
    data = event["data"]
    common = dict(
        status=Status.HYPOTHETICAL,
        level=Level.INSTANCE,
        environment=Environment(event.get("environment", "sandbox")),
        provenance=Provenance.ASSERTED,
        confidence=0.3,
        source_event_id=event["id"],
        valid_from=datetime.fromisoformat(event.get("validtime", event["time"])),
        recorded_at=now(),
    )
    bp = data["blueprint_id"]
    ports: dict[str, Port] = {}
    slots: list[Slot] = []
    for s in data["slots"]:
        sp = [
            Port(key=f"{bp}/{s['id']}.{p['name']}", name=p["name"], direction=p["direction"], **common)
            for p in s.get("ports", [])
        ]
        for p in sp:
            ports[p.key.split("/", 1)[1]] = p
        slots.append(Slot(key=f"{bp}/{s['id']}", role=s["role"], ports=sp, **common))

    couplings = [
        Coupling(
            key=f"{bp}/{c['id']}",
            type=CouplingType(c["type"]),
            source_port=ports[c["from"]],
            target_port=ports[c["to"]],
            **common,
        )
        for c in data["couplings"]
    ]
    return [*slots, *couplings]


async def run(event: dict) -> dict:
    """Write to the map and return the completion event data."""
    # TODO(step 4/5): run as a cognee Pipeline ending in add_data_points on dataset MAP_DATASET,
    # collect created/changed/retired ids, publish org.openreplicant.morphogen.pipeline.completed.
    points = to_datapoints(event)
    return {
        "pipeline": "blueprint",
        "run_id": event["id"],
        "dataset": "map",
        "status": "succeeded",
        "created": {"nodes": [str(p.id) for p in points], "edges": []},
        "changed": {"nodes": [], "edges": []},
        "retired": {"nodes": [], "edges": []},
        "labels": sorted({type(p).__name__ for p in points}),
    }
