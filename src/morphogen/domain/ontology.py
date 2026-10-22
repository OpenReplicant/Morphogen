"""Core ontology: slots and couplings.

Every node is a claim: it carries status, level, bitemporal times, provenance,
confidence and environment (decision records 0001 and 0007).

The types are plain pydantic models. References between claims are identity
keys, so a claim maps to one stored row and the store stays swappable
(decision 0011).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict


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
    return datetime.now(UTC)


# Fields every claim carries; the rest of a claim's fields are its content.
CLAIM_FIELDS = (
    "key", "status", "level", "environment", "provenance", "confidence",
    "source_event_id", "valid_from", "valid_to", "recorded_at", "retracted",
)


class Claim(BaseModel):
    """Fields every map node carries."""

    model_config = ConfigDict(use_enum_values=True)
    kind: ClassVar[str] = "Claim"

    key: str  # stable identity key (OTel resource attrs first, else source-scoped id)
    status: Status
    level: Level = Level.INSTANCE
    environment: Environment = Environment.SANDBOX
    provenance: Provenance
    confidence: float = 0.5
    source_event_id: str
    valid_from: datetime
    valid_to: datetime | None = None  # open interval = currently valid
    recorded_at: datetime
    retracted: bool = False

    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)
        cls.kind = cls.__name__

    def content(self) -> dict:
        """Everything except the claim fields; equal content means no change."""
        return self.model_dump(mode="json", exclude=set(CLAIM_FIELDS))

    def refs(self) -> list[tuple[str, str]]:
        """Outgoing references as (relation, target key): the graph edges of this node."""
        return []


class Contract(Claim):
    uri: str
    contract_kind: str  # asyncapi | openapi | mcp | jsonschema


class Port(Claim):
    slot: str  # owning slot key
    name: str
    direction: str  # in | out | inout
    contract: str | None = None  # contract URI

    def refs(self) -> list[tuple[str, str]]:
        return [("port_of", self.slot)]


class Requirement(Claim):
    description: str


class Capability(Claim):
    description: str


class Slot(Claim):
    role: str
    name: str  # name the slot is observed as: OTel service.name or span attr morphogen.slot
    cardinality: str = "exclusive"
    scope: str | None = None
    parent: str | None = None
    requirements: list[str] = []
    provider_hint: str | None = None

    def refs(self) -> list[tuple[str, str]]:
        return [("child_of", self.parent)] if self.parent else []


class Provider(Claim):
    """Fills a slot. level=type for catalog entries, instance for deployments."""

    name: str
    fills: str | None = None
    capabilities: list[str] = []
    catalog_entry: str | None = None  # instance -> type
    catalog_kinds: list[str] = []  # provider | transport | contract | pattern | ...
    trust: str | None = None

    def refs(self) -> list[tuple[str, str]]:
        return [("fills", self.fills)] if self.fills else []


class Coupling(Claim):
    """A node, not an edge (decision 0001).

    `source_slot`/`target_slot` are the slot names the coupling joins; drift
    compares couplings across statuses by these names because ports are not
    visible in traces.
    """

    coupling_type: CouplingType
    source_port: str | None = None
    target_port: str | None = None
    source_slot: str
    target_slot: str
    contract: str | None = None
    realization: str | None = None  # optional transport slot graph

    def refs(self) -> list[tuple[str, str]]:
        return [(r, k) for r, k in (("from", self.source_port), ("to", self.target_port)) if k]


class Hypothesis(Claim):
    statement: str
    proposal_event_id: str


class Prediction(Claim):
    hypothesis: str
    observation: str
    comparison: str
    value: Any = None
    window: str

    def refs(self) -> list[tuple[str, str]]:
        return [("predicts", self.hypothesis)]


class Experiment(Claim):
    hypothesis: str
    control: str | None = None
    commit: str | None = None
    verdict: str | None = None  # supported | refuted | inconclusive


KINDS: dict[str, type[Claim]] = {
    c.__name__: c
    for c in (Contract, Port, Requirement, Capability, Slot, Provider, Coupling,
              Hypothesis, Prediction, Experiment)
}


def from_row(kind: str, row: dict) -> Claim:
    return KINDS[kind].model_validate(row)
