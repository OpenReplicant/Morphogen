"""Kernel slot interfaces (rebuild 5).

Every concern in the kernel is a slot with one of these interfaces and a swappable provider.
Nothing here has a built-in handler. The wire formats in kernel/schemas/ are the source of truth
for every language; these Protocols are their Python shape.

Two kinds of slot:
  * Core slots (RecordStore, WritePipeline): swappable only by a provider that passes the
    conformance suite in kernel/contract/. Guarantees live in that suite, not in any provider.
  * Extension slots (everything else): attach at a hook point of the write pipeline or the read
    path, or run as a module kind (encoder, actuator, ...).

The one fixed rule (rebuild 4, D-86): no extension code runs inside the commit. Extensions act
before it (transform, veto, route) or after it (consume the change feed on a cursor). Anything an
extension produces after the commit re-enters at intake as a new proposal.

Ported from rebuild 4's kernel/contracts.py; ChainRunner dropped (parked since D-36); hook-point
and core-slot interfaces added.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping, Optional, Protocol, Sequence, runtime_checkable

JSON = Mapping[str, Any]
EvidenceType = Literal["deterministic", "extracted", "inferred", "observed", "testimony"]
Lane = Literal["auto", "review"]
HookEvent = Literal["session_start", "before_tool", "after_tool", "before_compact", "stop"]


# ================================================================ wire types (kernel/schemas/change_set.schema.json)
@dataclass
class Reference:
    source_uri: Optional[str] = None
    artifact: Optional[str] = None          # sha256 of a registered artifact
    quote: Optional[str] = None             # required when evidence_type == "extracted"
    quote_prefix: Optional[str] = None
    quote_suffix: Optional[str] = None
    span: Optional[JSON] = None             # Web Annotation selector, e.g. {"start": 10, "end": 42}


@dataclass
class Op:
    """One change-set operation. `body` holds the op-specific fields from the JSON Schema."""
    op: Literal["add_entity", "add_artifact", "add_claim", "set_status", "add_belief", "add_verification"]
    body: JSON = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"op": self.op, **self.body}


@dataclass
class ChangeSet:
    idempotency_key: str
    attributed_to: str                      # agent IRI mapped to the submitting identity
    generated_by: str                       # run id
    target_scope: str
    ops: list[Op]
    lane: Lane = "auto"

    def to_json(self) -> dict:
        return {
            "idempotency_key": self.idempotency_key,
            "attributed_to": self.attributed_to,
            "generated_by": self.generated_by,
            "target_scope": self.target_scope,
            "lane": self.lane,
            "ops": [o.to_json() for o in self.ops],
        }


@dataclass
class Submitted:
    id: str
    status: str
    lane: Lane


@dataclass
class Applied:
    """One entry of the change feed: a change set that was committed, or a redaction (R5-O3)."""
    seq: int                                # commit order; consumers keep a cursor
    kind: str                               # 'change_set' or 'redaction'
    change_set_id: Optional[str]            # None for a redaction
    scope: str
    claim_ids: Sequence[str]                # for a redaction, the claims whose content it removed
    predicates: Sequence[str]               # for cheap gating before any query
    target_kind: Optional[str] = None       # a redaction's target: 'claim' or 'artifact'
    target_id: Optional[str] = None


# ================================================================ core slots (conformance suite required)
@runtime_checkable
class RecordStore(Protocol):
    """Holds entities, claims, artifacts, runs and change sets with their append-only histories.
    Enforces clearance on every read. Default provider: kernel/providers/record-postgres."""

    def claims(self, **filters: str) -> list[JSON]: ...
    def claims_as_of(self, valid_at: Optional[str] = None, known_at: Optional[str] = None,
                     **filters: str) -> list[JSON]: ...           # bitemporal: true at valid_at, as recorded by known_at
    def explain(self, claim_id: str) -> JSON: ...
    def feed(self, after_seq: int, limit: int = 100) -> list[Applied]: ...   # change feed, cursor based


@runtime_checkable
class WritePipeline(Protocol):
    """The only path into the record: intake -> validation -> lane -> atomic commit.
    The commit runs no extension code."""

    def start_run(self, module: str, plan_step: Optional[str] = None,
                  used: Sequence[str] = (), info: Optional[JSON] = None) -> str: ...
    def finish_run(self, run_id: str, status: Literal["succeeded", "failed", "cancelled"],
                   cost: Optional[JSON] = None) -> None: ...
    def submit(self, change_set: ChangeSet) -> Submitted: ...


@runtime_checkable
class KernelClient(RecordStore, WritePipeline, Protocol):
    """What a module sees: read under its own identity, write only by submitting change sets."""


# ================================================================ hook points: before the commit
@dataclass
class FilterResult:
    action: Literal["pass", "transform", "drop"]
    change_set: Optional[ChangeSet] = None  # the transformed proposal when action == "transform"
    reason: str = ""


@runtime_checkable
class IntakeFilter(Protocol):
    """Hook: intake. Transform or drop a proposal (secrets, size, normalization)."""
    module: str
    def filter(self, change_set: JSON) -> FilterResult: ...


@dataclass
class ValidationResult:
    ok: bool
    report: JSON = field(default_factory=dict)


@runtime_checkable
class Validator(Protocol):
    """Hook: validation. May only veto. Never validates its own module's or agent's proposals."""
    module: str
    def validate(self, change_set: JSON) -> ValidationResult: ...


@runtime_checkable
class LanePolicy(Protocol):
    """Hook: lane. Routes a valid proposal to auto apply or review (e.g. autonomy level x risk class).
    Cannot apply anything itself."""
    module: str
    def route(self, change_set: JSON) -> Lane: ...


# ================================================================ hook points: after the commit
@runtime_checkable
class FeedConsumer(Protocol):
    """Hook: change feed. Reads applied change sets on its own cursor, asynchronously, and must be
    able to catch up after downtime. Writes only by submitting new change sets."""
    module: str
    def accepts(self, applied: Applied) -> bool: ...                  # cheap gate, no queries
    def consume(self, applied: Applied, run_id: str) -> Iterable[ChangeSet]: ...


# ================================================================ module kinds (rebuild 4, unchanged)
@runtime_checkable
class Encoder(Protocol):
    """Source -> change sets. Deterministic parsers set evidence_type 'deterministic';
    model extraction sets 'extracted' and must include quotes."""
    module: str
    def encode(self, source: str, run_id: str) -> Iterable[ChangeSet]: ...


@runtime_checkable
class Processor(FeedConsumer, Protocol):
    """Rebuild 4 name for a feed consumer that turns claims into change sets."""


@dataclass
class DecodeResult:
    media_type: str
    content: bytes
    unrepresented: list[str] = field(default_factory=list)   # what the target format cannot express


@runtime_checkable
class Decoder(Protocol):
    """Shaped claims (+ mappings) -> artifact in a target standard. Must report losses."""
    module: str
    target_format: str
    def decode(self, selection: JSON) -> DecodeResult: ...


@dataclass
class ActuationResult:
    external_refs: list[str]               # ids in the external runtime (commit, job, container)
    accepted: bool
    detail: str = ""


@runtime_checkable
class Actuator(Protocol):
    """Approved plan step -> effect in the world. Never submits claims; the effect is observed."""
    module: str
    allowed_actions: frozenset[str]
    def actuate(self, action: str, artifact: bytes, media_type: str) -> ActuationResult: ...


# ================================================================ slot-specific contracts
@dataclass
class Belief:
    value: float                            # 0..1
    explanation: JSON


@runtime_checkable
class BeliefModel(Protocol):
    module: str                             # model IRI recorded with every score
    def score(self, claim: JSON, evidence: Sequence[JSON]) -> Belief: ...
    def affected_by(self, changed_claims: Sequence[JSON]) -> list[str]: ...


@dataclass
class Verdict:
    verdict: Literal["supported", "refuted", "inconclusive"]
    details: JSON


@runtime_checkable
class Verifier(Protocol):
    module: str
    applies_to: frozenset[str]              # predicate IRIs or evidence types
    def verify(self, claim: JSON) -> Verdict: ...


@dataclass
class Scored:
    claim_id: str
    score: float


@runtime_checkable
class Recall(Protocol):
    """Read path: question -> ranked claims, under the reader's clearance."""
    module: str
    def recall(self, question: str, limit: int = 20, **filters: str) -> list[Scored]: ...


@runtime_checkable
class ContextAssembler(Protocol):
    module: str
    def assemble(self, task: str, budget_tokens: int) -> JSON: ...   # claims, entity cards, skills


@dataclass
class EvalScore:
    eval_set: str
    metric: str
    value: float
    details: JSON = field(default_factory=dict)


@runtime_checkable
class Evaluator(Protocol):
    """Scores a provider on an eval set; scores are recorded as claims. Evidence picks what fills
    a slot."""
    module: str
    def evaluate(self, provider: str, eval_set: str) -> list[EvalScore]: ...


@dataclass
class HookDecision:
    allow: bool = True
    inject_context: Optional[str] = None
    message: Optional[str] = None


@runtime_checkable
class HarnessAdapter(Protocol):
    """Maps kernel hook events onto one agent harness. Ergonomics only: clearance and attribution
    are enforced by the kernel, not here."""
    harness: str
    def install(self, profile: JSON, target_dir: str) -> list[str]: ...   # files written
    def on_event(self, event: HookEvent, payload: JSON) -> HookDecision: ...
