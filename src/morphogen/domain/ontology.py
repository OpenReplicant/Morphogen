"""Core ontology: slots and couplings, as cognee DataPoints.

Every node is a claim: it carries status, level, bitemporal times, provenance,
confidence and environment (decision records 0001 and 0007).

Spike note: field names follow our model; verify against the installed cognee
DataPoint base (import path, metadata/index_fields) during week 1.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Optional

from cognee.low_level import DataPoint


class Status(StrEnum):
    OBSERVED = "observed"
    INTENDED = "intended"
    HYPOTHETICAL = "hypothetical"


class Level(StrEnum):
    INSTANCE = "instance"
    TYPE = "type"


class Provenance(StrEnum):
    DISCOVERED = "discovered"
    ASSERTED = "asserted"
    INFERRED = "inferred"


class Environment(StrEnum):
    SANDBOX = "sandbox"
    STAGING = "staging"
    PRODUCTION = "production"


class CouplingType(StrEnum):
    CALL = "call"
    EVENT = "event"
    STREAM = "stream"
    SHARED_STATE = "shared_state"
    REQUEST_REPLY = "request_reply"


def now() -> datetime:
    return datetime.now(timezone.utc)


class Claim(DataPoint):
    """Fields every map node carries."""

    key: str  # stable identity key (OTel resource attrs first, else source-scoped id)
    status: Status
    level: Level = Level.INSTANCE
    environment: Environment = Environment.SANDBOX
    provenance: Provenance
    confidence: float = 0.5
    source_event_id: str
    valid_from: datetime
    valid_to: Optional[datetime] = None  # open interval = currently valid
    recorded_at: datetime
    retracted: bool = False


class Contract(Claim):
    uri: str
    kind: str  # asyncapi | openapi | mcp | jsonschema


class Port(Claim):
    name: str
    direction: str  # in | out | inout
    contract: Optional[Contract] = None


class Requirement(Claim):
    description: str


class Capability(Claim):
    description: str


class Slot(Claim):
    role: str
    cardinality: str = "exclusive"
    scope: Optional[str] = None
    parent: Optional["Slot"] = None
    ports: list[Port] = []
    requirements: list[Requirement] = []


class Provider(Claim):
    """Fills a slot. level=type for catalog entries, instance for deployments."""

    name: str
    fills: Optional[Slot] = None
    capabilities: list[Capability] = []
    catalog_entry: Optional["Provider"] = None  # instance -> type
    catalog_kinds: list[str] = []  # provider | transport | contract | pattern | ...
    trust: Optional[str] = None


class Coupling(Claim):
    """A node, not an edge (decision 0001)."""

    type: CouplingType
    source_port: Port
    target_port: Port
    contract: Optional[Contract] = None
    realization: Optional[Slot] = None  # optional transport slot graph


class Hypothesis(Claim):
    statement: str
    proposal_event_id: str


class Prediction(Claim):
    hypothesis: Hypothesis
    observation: str
    comparison: str
    value: str
    window: str


class Experiment(Claim):
    hypothesis: Hypothesis
    control: Optional[str] = None
    commit: Optional[str] = None
    verdict: Optional[str] = None  # supported | refuted | inconclusive
