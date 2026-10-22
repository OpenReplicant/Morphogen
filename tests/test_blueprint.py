"""Steps 4 and 5: blueprint -> hypothetical slots/couplings; completion events list the IDs."""

from morphogen.ingest.blueprint import to_datapoints

EXPECTED_COUPLINGS = {
    ("collector", "intake"), ("intake", "ingestor"), ("ingestor", "postgres"),
    ("map_mcp", "postgres"), ("map_mcp", "intake"), ("intake", "promoter"),
    ("ingestor", "drift-watcher"), ("drift-watcher", "postgres"), ("drift-watcher", "intake"),
    ("promoter", "postgres"), ("promoter", "intake"),
    ("promoter", "orchestrator"), ("orchestrator", "docker"),
}


def test_blueprint_maps_to_slots_and_couplings(blueprint):
    points = to_datapoints(blueprint)
    kinds = [p.kind for p in points]
    assert kinds.count("Slot") == 9
    assert kinds.count("Coupling") == 13
    assert kinds.count("Port") == 22
    assert all(p.status == "hypothetical" and p.provenance == "asserted" for p in points)
    pairs = {(p.source_slot, p.target_slot) for p in points if p.kind == "Coupling"}
    assert pairs == EXPECTED_COUPLINGS


def test_submitting_blueprint_writes_the_map(client, rt, blueprint):
    assert client.post("/events", json=blueprint).status_code == 202
    slots = rt.store.query(kind="Slot", status="hypothetical")
    assert sorted(s.name for s in slots) == ["collector", "docker", "drift-watcher", "ingestor",
                                             "intake", "map_mcp", "orchestrator", "postgres",
                                             "promoter"]
    pairs = {(c.source_slot, c.target_slot) for c in rt.store.query(kind="Coupling")}
    assert pairs == EXPECTED_COUPLINGS
    port = next(p for p in rt.store.query(kind="Port") if p.key == "morphogen-self/intake.events_in")
    assert port.contract == "contracts/intake.asyncapi.yaml"


def test_completion_event_lists_created_ids(client, rt, blueprint):
    client.post("/events", json=blueprint)
    [done] = [e for e in rt.router.archive.read("completions") if e["data"]["pipeline"] == "blueprint"]
    assert done["causationid"] == blueprint["id"]
    assert done["data"]["status"] == "succeeded"
    stored = {c.key for c in rt.store.query()}
    assert set(done["data"]["created"]["nodes"]) == stored
    assert "morphogen-self/c3|to|morphogen-self/postgres.sql" in done["data"]["created"]["edges"]
    assert done["data"]["labels"] == ["Coupling", "Port", "Slot"]


def test_resubmission_is_idempotent_and_retires_removed_parts(client, rt, blueprint):
    client.post("/events", json=blueprint)
    again = {**blueprint, "id": "bp-self-0002"}
    client.post("/events", json=again)
    second = rt.router.archive.read("completions")[-1]
    assert second["data"]["created"]["nodes"] == [] and second["data"]["changed"]["nodes"] == []

    smaller = {**blueprint, "id": "bp-self-0003",
               "data": {**blueprint["data"],
                        "couplings": [c for c in blueprint["data"]["couplings"] if c["id"] != "c6"]}}
    client.post("/events", json=smaller)
    done = [e for e in rt.router.archive.read("completions") if e["data"]["pipeline"] == "blueprint"][-1]
    assert done["data"]["retired"]["nodes"] == ["morphogen-self/c6"]
    assert "morphogen-self/c6" not in {c.key for c in rt.store.query(kind="Coupling")}
