import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = json.loads((ROOT / "examples" / "self-blueprint.json").read_text())


def test_blueprint_event_is_valid():
    from fastapi.testclient import TestClient
    from morphogen.intake.app import app

    r = TestClient(app).post("/events", json=BLUEPRINT)
    assert r.status_code == 202, r.text


def test_invalid_event_rejected():
    from fastapi.testclient import TestClient
    from morphogen.intake.app import app

    bad = {**BLUEPRINT, "type": "something.else"}
    assert TestClient(app).post("/events", json=bad).status_code == 400


@pytest.mark.skip(reason="needs cognee DataPoint import verified in the spike")
def test_blueprint_maps_to_slots_and_couplings():
    from morphogen.ingest.blueprint import to_datapoints

    points = to_datapoints(BLUEPRINT)
    kinds = [type(p).__name__ for p in points]
    assert kinds.count("Slot") == 6
    assert kinds.count("Coupling") == 6
    assert all(p.status == "hypothetical" for p in points)
