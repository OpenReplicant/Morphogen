"""The evidence log's records, as a caller reads them (PLAN.md, phase 7a): a published, versioned schema, so a
system that calls the judge can check a verdict and verify the log without importing Morphogen.

    python -m morphogen.schema > schemas/evidence-record.v1.json     # regenerate the published file

The log (evidence.py): each record is a JSON object stored as its canonical JSON (keys sorted, separators
"," and ":", UTF-8 not escaped). `hash` is the SHA-256 of the canonical JSON of the record without `hash`;
`prev` is the previous record's `hash` ("0" * 64 for the first); `seq` counts from 1. A reader verifies the
chain by recomputing each hash in `seq` order. Fields not listed here may appear; a reader keeps them.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

VERSION = "evidence-record/v1"


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class Refs(_Open):
    base: str = Field(description="the base commit, in full")
    candidate: str = Field(description="the candidate commit, in full")


class Gate(_Open):
    decision: str = Field(description="who may merge a pass: merge (an agent may), review (a person merges), or none")


class RequestRef(_Open):
    digest: str = Field(description="SHA-256 of the request's canonical JSON")
    version: str = Field(description="the request format, e.g. request/v1")
    kind: Literal["judge", "change", "probe", "measure"]


class Record(_Open):
    """Every record: what the log guarantees for any kind."""
    seq: int = Field(ge=1)
    at: str = Field(description="UTC, ISO 8601 to the second, e.g. 2026-11-11T14:47:02Z")
    prev: str = Field(min_length=64, max_length=64)
    hash: str = Field(min_length=64, max_length=64)
    claim: str
    by: str = Field(description="who wrote it; only `judge` writes measured or simulated records")
    trust: Literal["measured", "simulated", "stated", "inferred", "asserted"]
    kind: str | None = Field(None, description="verdict, probe, measurement, or a caller's own kind")


class ServedEnv(_Open):
    pass_: list[str] = Field(alias="pass", description="the names every run got as environment variables")
    public: list[str] = Field(description="the names whose values were not scanned for in the runs' output")
    digest: str = Field(min_length=64, max_length=64, description="SHA-256 of the canonical JSON of every served name and value")


class ServedService(_Open):
    image: str = Field(description="the image as the operator named it")
    id: str = Field(description="the image's id, resolved once; every run's service started from it")
    env: list[str] = Field(description="the names the service got")


class Served(_Open):
    env: ServedEnv | None = None
    services: dict[str, ServedService] | None = None


class Verdict(Record):
    """A record of kind `verdict`: the judge's answer on a candidate against a base."""
    kind: Literal["verdict"]
    verdict: Literal["pass", "fail"]
    subject: dict[str, Any] = Field(description="system: the cell or cells; path: cell:NAME, or change")
    method: str
    outcome: dict[str, Any] = Field(description="what was measured and checked; its keys depend on the method")
    refs: Refs
    gate: Gate | dict[str, Any]
    sandbox: str = Field(description="the runner the judge used: none, podman or docker")
    runner: dict[str, Any] = Field(description="the guarantees that runner gives")
    settings: dict[str, Any] | None = Field(None, description="the judge's settings for this run (trunk, sandbox, sandbox_image, budget)")
    settings_from: dict[str, str] | None = Field(None, description="per setting: base (the base commit's morphogen.yaml), morphogen.local.yaml, request, or default")
    request: RequestRef | None = None
    served: Served | None = Field(None, description="what the runs were given beyond their tree (morphogen.local.yaml's env and services); names, a digest and image ids, never a value")
    parameters: dict[str, Any] | list[Any] | None = None
    labels: dict[str, str] | None = Field(None, description="the caller's labels; never decide the verdict")


def json_schema() -> dict:
    s = Verdict.model_json_schema()
    s["$id"] = "https://github.com/OpenReplicant/Morphogen/blob/main/schemas/evidence-record.v1.json"
    s["title"] = "A verdict in Morphogen's evidence log (evidence-record/v1)"
    s["description"] = (__doc__ or "").split("\n\n", 2)[2].strip()
    return s


if __name__ == "__main__":
    print(json.dumps(json_schema(), indent=2, sort_keys=True))
