"""CloudEvents intake: validate, archive, route.

Accepts structured-mode CloudEvents (application/cloudevents+json). Telemetry
does not come here; it enters through the OTel Collector.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from jsonschema import Draft202012Validator

from morphogen import EVENT_TYPE_PREFIX

SCHEMAS = Path(__file__).resolve().parents[3] / "schemas" / "events"

ENVELOPE = Draft202012Validator(json.loads((SCHEMAS / "cloudevents-extensions.json").read_text()))
DATA_SCHEMAS = {
    "blueprint.submitted": "blueprint-submitted.schema.json",
    "proposal.created": "proposal-created.schema.json",
    "pipeline.completed": "pipeline-completed.schema.json",
}
VALIDATORS = {
    k: Draft202012Validator(json.loads((SCHEMAS / v).read_text())) for k, v in DATA_SCHEMAS.items()
}

app = FastAPI(title="morphogen-intake")


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.post("/events", status_code=202)
async def receive(request: Request) -> dict:
    event = await request.json()
    errors = [e.message for e in ENVELOPE.iter_errors(event)]
    short = event.get("type", "").removeprefix(EVENT_TYPE_PREFIX)
    if short in VALIDATORS:
        errors += [e.message for e in VALIDATORS[short].iter_errors(event.get("data"))]
    if errors:
        raise HTTPException(status_code=400, detail=errors)

    # TODO(step 3): archive raw event (object store), then route.
    # TODO(step 4): router.dispatch(event) -> ingestors for this type + subscribed watchers.
    return {"accepted": event["id"]}
