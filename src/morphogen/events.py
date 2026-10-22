"""CloudEvents: construction and validation against `schemas/events/`."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from morphogen import EVENT_TYPE_PREFIX

SCHEMAS = Path(os.environ.get("MORPHOGEN_SCHEMAS",
                              Path(__file__).resolve().parents[2] / "schemas" / "events"))

# Every event type the intake accepts, with its data schema (contracts/intake.asyncapi.yaml).
DATA_SCHEMAS = {
    "blueprint.submitted": "blueprint-submitted.schema.json",
    "proposal.created": "proposal-created.schema.json",
    "proposal.decided": "proposal-decided.schema.json",
    "finding.created": "finding-created.schema.json",
    "assertion.created": "assertion-created.schema.json",
    "intent.committed": "intent-committed.schema.json",
    "pipeline.completed": "pipeline-completed.schema.json",
}

# Not accepted at the public /events endpoint: decisions come through the authenticated review
# route; intent.committed and pipeline.completed are published in-process by the promoter and
# ingestors only.
INTERNAL_TYPES = {"proposal.decided", "intent.committed", "pipeline.completed"}

_FORMATS = FormatChecker()
ENVELOPE = Draft202012Validator(json.loads((SCHEMAS / "cloudevents-extensions.json").read_text()),
                                format_checker=_FORMATS)
VALIDATORS = {
    k: Draft202012Validator(json.loads((SCHEMAS / v).read_text()), format_checker=_FORMATS)
    for k, v in DATA_SCHEMAS.items()
}


def short_type(event: dict) -> str:
    return str(event.get("type", "")).removeprefix(EVENT_TYPE_PREFIX)


def validate(event: dict) -> list[str]:
    """Schema errors for an event; empty means valid. Unknown types are rejected."""
    if not isinstance(event, dict):
        return ["event must be a JSON object"]
    errors = [f"{'/'.join(map(str, e.path)) or 'envelope'}: {e.message}" for e in ENVELOPE.iter_errors(event)]
    short = short_type(event)
    if short not in VALIDATORS:
        errors.append(f"unknown event type: {event.get('type')!r}")
    else:
        errors += [f"data/{'/'.join(map(str, e.path))}: {e.message}"
                   for e in VALIDATORS[short].iter_errors(event.get("data"))]
    return errors


def make(short: str, source: str, data: dict, *, environment: str = "sandbox",
         causationid: str | None = None, **ext) -> dict:
    event = {
        "specversion": "1.0",
        "id": str(uuid.uuid4()),
        "source": source,
        "type": EVENT_TYPE_PREFIX + short,
        "time": datetime.now(UTC).isoformat(),
        "datacontenttype": "application/json",
        "environment": environment,
        **({"causationid": causationid} if causationid else {}),
        **ext,
        "data": data,
    }
    return event


def parse_time(value: str) -> datetime:
    t = datetime.fromisoformat(value)
    return t if t.tzinfo else t.replace(tzinfo=UTC)
