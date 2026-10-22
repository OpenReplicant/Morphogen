"""morphogen-map MCP server: read the map, propose changes.

Harness-agnostic. Read tools query the map (read-only role); the only write is
`propose`, which sends a CloudEvent to the intake. It never writes the map,
the database or intent/.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from mcp.server.fastmcp import FastMCP

from morphogen import EVENT_TYPE_PREFIX

INTAKE_URL = os.environ.get("MORPHOGEN_INTAKE_URL", "http://localhost:8080/events")
AGENT_ID = os.environ.get("MORPHOGEN_AGENT_ID", "agent:unknown")

mcp = FastMCP("morphogen-map")


@mcp.tool()
async def status(target: str) -> dict:
    """Kill-switch state, autonomy level and open proposals for a target."""
    # TODO(step 6): read from the promoter's policy state (read-only).
    return {"target": target, "kill_switch": False, "autonomy": "L0", "open_proposals": []}


@mcp.tool()
async def slots(target: str, status: str | None = None) -> list[dict]:
    """List slots for a target, optionally filtered by claim status."""
    # TODO(step 6): query the map (cognee search or AGE Cypher via read-only role).
    return []


@mcp.tool()
async def couplings(target: str, slot: str | None = None) -> list[dict]:
    """List couplings for a target or a slot, with type and contract."""
    return []


@mcp.tool()
async def drift(target: str, environment: str = "sandbox") -> dict:
    """Intended-not-observed and observed-not-intended claims at the current valid time."""
    return {"intended_not_observed": [], "observed_not_intended": []}


@mcp.tool()
async def blast_radius(slot_keys: list[str]) -> dict:
    """Slots reachable from the given slots through couplings."""
    return {"affected": []}


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
) -> dict:
    """Send a proposal to the intake. Needs at least one testable prediction."""
    event = {
        "specversion": "1.0",
        "id": str(uuid.uuid4()),
        "source": AGENT_ID,
        "type": EVENT_TYPE_PREFIX + "proposal.created",
        "time": datetime.now(timezone.utc).isoformat(),
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
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat(),
        },
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(INTAKE_URL, json=event, headers={"content-type": "application/cloudevents+json"})
    return {"status": r.status_code, "body": r.json() if r.content else None, "id": event["id"]}


if __name__ == "__main__":
    mcp.run()
