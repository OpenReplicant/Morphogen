"""morphogen-map MCP server: read the map, propose changes.

Harness-agnostic. Read tools query the map through a store opened with the
read-only role (MORPHOGEN_READ_DATABASE_URL); governance status comes from the
intake's read-only review API. The only write is `propose`, which sends a
CloudEvent to the intake. It never writes the map, the database or intent/.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from mcp.server.mcpserver import MCPServer

from morphogen import EVENT_TYPE_PREFIX, queries, telemetry
from morphogen.store import MapStore, open_store

INTAKE_URL = os.environ.get("MORPHOGEN_INTAKE_URL", "http://localhost:8080/events")
AGENT_ID = os.environ.get("MORPHOGEN_AGENT_ID", "agent:unknown")
SLOT = "map_mcp"

mcp = MCPServer("morphogen-map")
_store: MapStore | None = None


def store() -> MapStore:
    global _store
    if _store is None:
        dsn = os.environ.get("MORPHOGEN_READ_DATABASE_URL")  # never the writer DSN
        if dsn:
            from morphogen.store.postgres import PostgresStore

            _store = PostgresStore(dsn, slot=SLOT)
        else:
            _store = open_store()  # empty in-process store: nothing to read
    return _store


def set_store(s: MapStore) -> None:
    global _store
    _store = s


def _intake_base() -> str:
    return INTAKE_URL.rsplit("/events", 1)[0]


@mcp.tool()
async def status(target: str) -> dict:
    """Kill-switch state, autonomy level and open proposals for a target."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{_intake_base()}/review/status/{target}")
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        # Unknown governance state: treat as stopped, never as permission.
        return {"target": target, "kill_switch": None, "autonomy": None, "open_proposals": [],
                "error": f"review API unreachable: {e}"}


@mcp.tool()
async def slots(target: str, status: str | None = None, environment: str = "sandbox") -> list[dict]:
    """List slots for a target, optionally filtered by claim status (observed, intended, hypothetical)."""
    with telemetry.span("tool slots", SLOT):
        return queries.slots(store(), environment, status)


@mcp.tool()
async def couplings(target: str, slot: str | None = None, environment: str = "sandbox") -> list[dict]:
    """List couplings for a target or a slot name, with type, status and ports."""
    with telemetry.span("tool couplings", SLOT):
        return queries.couplings(store(), environment, slot)


@mcp.tool()
async def drift(target: str, environment: str = "sandbox") -> dict:
    """Intended-not-observed and observed-not-intended claims at the current valid time."""
    with telemetry.span("tool drift", SLOT):
        return queries.drift(store(), environment)


@mcp.tool()
async def blast_radius(slot_keys: list[str], environment: str = "sandbox") -> dict:
    """Slots reachable from the given slot names through couplings."""
    with telemetry.span("tool blast_radius", SLOT):
        return queries.blast_radius(store(), slot_keys, environment)


@mcp.tool()
async def metrics(target: str, environment: str = "sandbox") -> dict:
    """Map quality: coverage, precision, freshness and drift counts."""
    with telemetry.span("tool metrics", SLOT):
        return queries.metrics(store(), environment)


def proposal_event(target: str, summary: str, change: dict, risk: str, hypothesis: str,
                   predictions: list[dict], evidence: list[str], ttl_hours: int = 24,
                   rollback: str | None = None) -> dict:
    t = datetime.now(UTC)
    return {
        "specversion": "1.0",
        "id": str(uuid.uuid4()),
        "source": AGENT_ID,
        "type": EVENT_TYPE_PREFIX + "proposal.created",
        "time": t.isoformat(),
        "datacontenttype": "application/json",
        "environment": change.get("environment", "sandbox"),
        "claimstatus": "hypothetical",
        "data": {
            "target": target,
            "summary": summary,
            "change": change,
            "risk": risk,
            "hypothesis": hypothesis,
            "predictions": predictions,
            "evidence": evidence,
            **({"rollback": rollback} if rollback else {}),
            "expires_at": (t + timedelta(hours=ttl_hours)).isoformat(),
        },
    }


@mcp.tool()
async def propose(
    target: str,
    summary: str,
    change: dict,
    risk: str,
    hypothesis: str,
    predictions: list[dict],
    evidence: list[str],
    ttl_hours: int = 24,
    rollback: str | None = None,
) -> dict:
    """Send a proposal to the intake. Needs at least one testable prediction.

    change: {kind, environment, files: [{path, content}], affected_slots}; paths start with
    base/, environments/ or experiments/. A 400 lists schema errors to fix.
    """
    event = proposal_event(target, summary, change, risk, hypothesis, predictions, evidence,
                           ttl_hours, rollback)
    with telemetry.client_span("propose", SLOT, "intake", **{"messaging.system": "cloudevents"}):
        headers = telemetry.inject({"content-type": "application/cloudevents+json"})
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(INTAKE_URL, json=event, headers=headers)
    return {"status": r.status_code, "body": r.json() if r.content else None, "id": event["id"]}


if __name__ == "__main__":
    telemetry.setup(SLOT)
    mcp.run()
