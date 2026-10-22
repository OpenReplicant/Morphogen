"""Step 3: the intake validates CloudEvents against schemas/events/ and archives them."""

from morphogen.events import make


def test_valid_event_accepted_and_archived(client, rt, blueprint):
    r = client.post("/events", json=blueprint)
    assert r.status_code == 202, r.text
    archived = rt.router.archive.read("events")
    assert [e["id"] for e in archived if e["type"] == blueprint["type"]] == [blueprint["id"]]


def test_unknown_type_rejected(client, blueprint):
    r = client.post("/events", json={**blueprint, "type": "org.openreplicant.morphogen.nope"})
    assert r.status_code == 400
    assert any("unknown event type" in e for e in r.json()["detail"])


def test_missing_envelope_attribute_rejected(client, blueprint):
    bad = {k: v for k, v in blueprint.items() if k != "environment"}
    assert client.post("/events", json=bad).status_code == 400


def test_invalid_data_rejected_and_not_archived(client, rt, blueprint):
    blueprint["data"]["couplings"][0]["type"] = "telepathy"
    assert client.post("/events", json=blueprint).status_code == 400
    assert rt.router.archive.read("events") == []


def test_dangling_port_reference_rejected(client, blueprint):
    blueprint["data"]["couplings"][0]["to"] = "intake.nowhere"
    r = client.post("/events", json=blueprint)
    assert r.status_code == 400 and "unknown port" in r.text


def test_not_json_rejected(client):
    assert client.post("/events", content=b"{nope").status_code == 400


def test_proposal_without_prediction_rejected(client):
    e = make("proposal.created", "agent:test", {
        "target": "morphogen-self", "summary": "s", "risk": "low", "hypothesis": "h",
        "change": {"kind": "config", "files": []}, "predictions": [], "evidence": [],
        "expires_at": "2099-01-01T00:00:00Z"})
    assert client.post("/events", json=e).status_code == 400
