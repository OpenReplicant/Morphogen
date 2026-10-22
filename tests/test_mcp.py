"""Step 6: the map MCP server lists the blueprint and sends a valid proposal."""

import socket
import threading
import time

import pytest
import uvicorn

from morphogen.intake.app import create_app
from morphogen.mcp import server


@pytest.fixture
def live_intake(rt, monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(create_app(rt, sweep_interval_s=0), port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    while not srv.started:
        time.sleep(0.01)
    monkeypatch.setattr(server, "INTAKE_URL", f"http://127.0.0.1:{port}/events")
    server.set_store(rt.store)
    yield rt
    srv.should_exit = True
    t.join(5)


async def test_tools_registered():
    names = {t.name for t in await server.mcp.list_tools()}
    assert {"status", "slots", "couplings", "drift", "blast_radius", "metrics", "propose"} <= names


async def test_list_blueprint_and_propose(live_intake, blueprint):
    rt = live_intake
    rt.submit(blueprint)

    slots = await server.slots("morphogen-self", status="hypothetical")
    assert len(slots) == 7
    couplings = await server.couplings("morphogen-self", slot="postgres")
    assert {c["source_slot"] for c in couplings} == {"ingestor", "map_mcp", "drift-watcher", "promoter"}
    radius = await server.blast_radius(["promoter"])
    assert radius["affected"][0] == {"slot": "intake", "depth": 1}
    assert (await server.status("morphogen-self"))["autonomy"] == "L0"

    r = await server.propose(
        target="morphogen-self", summary="Add an echo service to sandbox",
        change={"kind": "add_provider", "environment": "sandbox", "affected_slots": ["echo"],
                "files": [{"path": "environments/sandbox/echo/compose.yml", "content": "services: {}\n"}]},
        risk="low", hypothesis="h",
        predictions=[{"observation": "slot:echo observed", "comparison": "exists", "value": True,
                      "window": "PT10M"}],
        evidence=["morphogen-self/promoter"])
    assert r["status"] == 202, r
    assert rt.promoter.state.get(r["id"]).state == "pending"

    bad = await server.propose(target="morphogen-self", summary="x", change={"kind": "config", "files": []},
                               risk="low", hypothesis="h", predictions=[], evidence=[])
    assert bad["status"] == 400


async def test_status_unreachable_is_not_permission(monkeypatch):
    monkeypatch.setattr(server, "INTAKE_URL", "http://127.0.0.1:9/events")
    s = await server.status("morphogen-self")
    assert s["kill_switch"] is None and "error" in s
