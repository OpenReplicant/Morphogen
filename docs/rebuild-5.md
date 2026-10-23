# Rebuild 5: kernel and Morphogen carry-over map

Repo copy of the "Rebuild 5: Kernel and Morphogen Carry-Over Map" doc (Oct 23, 2026). Rebuild 5 keeps the
kernel's guarantees, changes its module boundary, and ships one distribution: Morphogen, a system you
describe that builds and manages it, starting with itself.

## What makes this different

cognee and Graphiti are memory systems where the model's output becomes the record. The kernel is a record
where model output is only ever a proposal. Everything distinctive follows from that inversion.

Each property either **forbids** something (a guarantee) or **adds** something (a feature). Features can live
in any module on any system. Guarantees cannot be added from outside: if something else can write around a
module, the module is advisory. So the forbids rows define the kernel; the adds rows are slots.

| Property | cognee / Graphiti | Kernel | Kind |
| --- | --- | --- | --- |
| Who decides what is true | The pipeline: an LLM extracts, dedupes and invalidates, and the result is applied | Models propose; validation, belief and people decide | Forbids |
| How writes happen | Many write methods, straight to the store | One path: proposal → validation → lane → atomic commit | Forbids |
| Attribution | Episode or dataset provenance | Every claim has agent, run and reference; extracted claims carry their quote | Forbids |
| History | Graphiti invalidates edges but rewrites node summaries; cognee's `forget` deletes | Nothing deleted; status and belief are append-only; redaction is a recorded act | Forbids |
| Clearance | Groups or datasets in application code | Scopes enforced by the store; derived claims never wider than their inputs | Forbids |
| Separation of duties | None | No self-validation, self-approval or self-verification | Forbids |
| Belief | None, or the LLM's judgment | Swappable model over support and contradiction, separate from clearance | Adds |
| Ingestion | LLM-centric | Deterministic encoders first; models at the edges | Adds |
| Ontology | Ad hoc types or learned labels | Terms from official catalogs, gated, extended through review | Adds |
| Recall | Hybrid search, MCP | Hybrid search, MCP, measured on public benchmarks | Adds |
| Self-description | None | The kernel is its own blueprint of slots, under the same governance | Adds |

## Kernel shape

The kernel is a blueprint, not a monolith: every concern is a named slot with an interface and a default
provider, and nothing has a handler built in. Guarantees are not implementations; they are a conformance
suite that any provider of a core slot must pass.

| Part | What it is | Changes how |
| --- | --- | --- |
| Conformance contract (`kernel/contract/`) | The invariants as named, executable cases | Only by an owner decision with evidence |
| Self-blueprint (`kernel/blueprint/slots.yaml`) | The kernel's own slots and couplings, recorded as claims | Additive changes freely; breaking changes versioned |
| Default providers (`kernel/providers/`) | One implementation per slot | Swapped if the replacement passes the contract and wins on evals |

### Hook points: extensions act before or after the commit, never inside it

```
 Before the commit: may transform or veto                      After: cannot block writes
 ┌─────────┐   ┌────────────┐   ┌──────────┐   ┌──────────────┐   ┌──────────────────┐
 │ Intake  │──▶│ Validation │──▶│   Lane   │──▶│    Commit    │──▶│   Change feed    │
 │normalize│   │ veto only, │   │auto apply│   │atomic apply, │   │ async consumers  │
 │ filter  │   │never own   │   │or review │   │no extensions │   │ on a cursor      │
 └────▲────┘   └────────────┘   └──────────┘   └──────────────┘   └────────┬─────────┘
      └──────────── belief, findings and plans re-enter as new proposals ──┘
```

| Stage | Hook point | Extensions may | Runs |
| --- | --- | --- | --- |
| Intake | normalize, filter (secrets, size) | Transform or drop a proposal | Before validation |
| Validation | validators, shape checks, policy | Veto, never approve their own | Before commit |
| Lane | autonomy and risk policy | Route to auto apply or review | Before commit |
| Commit | none | Nothing: atomic apply only | Core |
| Change feed | consumers on a cursor | Score belief, update projections and indexes, wake watchers, notify | After commit, asynchronous, each able to catch up |
| Read | recall, context assembly, views | Rank, assemble, render under the reader's clearance | On request |

## Carry-over map

Rebuild 4 (OpenReplicant/kernel) is a read-only reference. **Port** = largely as is. **Rewrite** = keep the
purpose, change the shape. **Park** = not in the first distribution. **Drop** = not carried.

### Core

| Part | Verdict | Status in this repo |
| --- | --- | --- |
| `kernel/schema/001_kernel.sql`, `002_bootstrap.sql` | Port as the default record-store and pipeline provider | Ported: `kernel/providers/record-postgres/schema/` |
| `kernel/schema/tests` (30 checks) | Into the conformance suite | Done: `kernel/contract/invariants.yaml` names all 30; `run.sh` passes 30/30 and fails on a disabled quote check |
| `eval/validator`, `eval/belief-v0` | Into the conformance suite | Done (T2): `kernel/contract/slots/validator` (13) and `slots/belief-model` (17), passed by the ported providers |
| `kernel/contracts.py` | Rewrite as slot interfaces | Done: `kernel/src/kk/interfaces.py` |
| `kernel/schemas` (change set, module manifest) | Port, then adapt | Ported: `kernel/schemas/` |
| `ontology/slots.yaml` (42 slots) | Rewrite as the self-blueprint | Done for kernel slots: `kernel/blueprint/slots.yaml`; original kept in `docs/slots-rebuild4.yaml` |
| `ontology` packs | Port; RDF at the edges | Ported: `kernel/packs/` |
| `shapes/` (SHACL) | Rewrite as one validator provider | To do |
| `kk` command | Rewrite, smaller | To do |
| `docs/LESSONS.md` | Port whole | Ported |
| `docs/decisions.md` (D-01 to D-93) | Keep as history | Referenced from `docs/decisions.md` |
| `parked/` | Drop | — |

### Modules

| Module (rebuild 4) | Verdict | Goes to |
| --- | --- | --- |
| kernel-mcp | Port | `kernel/providers/` (agent-interface slot) |
| validator-shacl | Rewrite | `kernel/providers/` (validator candidate) |
| belief-corroboration, verifier-quotes | Port | `kernel/providers/` |
| truth-maintenance, kernel-mcp briefing | Park: their slots stay unfilled (R5-12) | — |
| recall-index, recall-dense | Port | `kernel/providers/` |
| evaluator | Port, central | `kernel/providers/` |
| self-encoder | Rewrite | `kernel/providers/` (encodes blueprint, providers, packs) |
| ingest-filter-gitleaks, pack-loader | Port | `kernel/providers/` |
| encoder-interaction, skill-interview, map-gaps | Port | `morphogen/modules/` (design agent) |
| observer-prometheus, anomaly | Port; add an OTel observer | `morphogen/modules/` |
| skill-adaptation-planning | Rewrite: predictions and risk class | `morphogen/modules/` |
| actuator-compose | Rewrite: intent actuator | `morphogen/modules/` |
| ui, view-modules | Rewrite: window-manager shell | `morphogen/ui/` |
| encoder-eventlog, encoder-bpmn, conformance, learner-process, view-bpm, view-devops | Park | — |
| encoder-papers, memory-extractor | Park; evals stay as baselines | — |

### Evals

| Eval | Verdict |
| --- | --- |
| validator, belief-v0 | Into the conformance suite |
| self-model questions | Port; the self-modifying gate builds on it |
| SciFact, LongMemEval, RCAEval | Port as baselines the new build must match |
| BPI Challenge 2019 | Park |

## Morphogen, the only distribution

### Bootstrap set

A system that builds systems cannot build its own first parts. These ship in place; everything after them
arrives through the loop.

| Slot | Bootstrap provider | Source |
| --- | --- | --- |
| Record store and write pipeline | Postgres claims, change sets, lanes | Ported |
| Conformance suite | Invariant tests | Ported |
| Design agent | Interview and blueprint encoder, map gaps | To port |
| Monitor | OTel observer, Prometheus observer | New, to port |
| Analyse | Anomaly detection, watchers on the change feed | To port |
| Plan | Planning skill with predictions and risk class | To rewrite |
| Review lane | Autonomy level × risk class | To rewrite |
| Execute | Intent actuator: commits to git, orchestrators reconcile | To rewrite |
| Verify | Separate verifier compares observations with predictions | New |
| Evaluator | Scores a candidate against the incumbent | To port |
| Catalog lookup | Configured registries, matched on slot requirements | New |
| Recall and MCP | BM25 recall, kernel MCP | To port |

Any later provider, including replacements for bootstrap ones, arrives the same way: proposed against a slot,
built or found in a catalog, installed in a sandbox, scored by the evaluator, approved, observed.

## Baselines to reproduce and beat

cognee and Graphiti are studied, not depended on. Both are Apache-2.0: borrowing ideas is free, and copied
code keeps their notice.

| Area | Baseline | Where we try to beat it | Measure |
| --- | --- | --- | --- |
| Entity recognition and linking | Free-form LLM extraction with LLM dedup | Ontology-constrained extraction; linking to catalog identifiers; small models with quotes checked in code; ambiguous matches kept for review | Entity and link precision and recall; share linked to official identifiers |
| Ontology management | Ad hoc or learned types | Terms from LOV, OBO, BioPortal; approved-predicate gate; proposals and mappings through review | Term reuse; mapping precision; duplicate proposals |
| Contradiction and change | Graphiti's automatic invalidation | Invalidation as a proposal, resolved by evidence or review | Current-state accuracy over time; wrong invalidations avoided |
| Recall | Graphiti hybrid search; cognee graph completion | Ported BM25, dense fusion, re-ranking (LongMemEval 0.10 → 0.62 with a 2.6B reader) | LongMemEval, SciFact, same splits |
| Belief | None | Corroboration with copy detection (D-62) | belief-v0; SciFact verdicts |

Rules from rebuild 4: tune on train, report on dev (D-64); opaque item keys (D-65); a green eval counts only
after it has failed with the logic broken.

## Gates and the stop rule

| Gate | Passes when |
| --- | --- |
| G1 Contract | The conformance suite passes on the default providers and fails when any check is disabled |
| G2 Self-modifying | Morphogen proposes a change to one of its own providers, builds it, installs it in a sandbox, the evaluator scores it above the incumbent, a person approves, the intent actuator commits it, and the observed result matches the predictions. Every step cites claims |
| G3 Someone else's system | Morphogen maps a small real system it did not build and completes one governed change on it |

- No redesign of the kernel until G1 passes; no redesign of Morphogen until G2 passes.
- New ideas go into `docs/decisions.md` as proposed entries, checked against D-01 to D-93 first.
- Rebuild 4's eval numbers are the floor.

## First tasks

| ID | Task | Check |
| --- | --- | --- |
| T1 | Add the three pending contract cases (feed cursor, bitemporal as-of, no extension in commit) to `invariants.yaml` and the record-postgres suite, with the applied-sequence cursor from D-86 | `kernel/contract/run.sh` passes; mutation check fails. **Done** (R5-10): 54/54; all 14 mutants in `tests/mutants.py` fail |
| T2 | Port `eval/validator` and `eval/belief-v0` into the contract | Same. **Done** (R5-11): 13/13 and 17/17 on validator-shacl and belief-corroboration; 30/30 mutants fail across providers |
| T3 | Port kernel-mcp, recall-bm25, belief-corroboration, verifier-quotes, evaluator into `kernel/providers/` against `kk.interfaces` | Each module's tests; recall matches rebuild 4 on SciFact |
| T4 | Rewrite the self-encoder: encode `kernel/blueprint/slots.yaml` and `morphogen/distribution.yaml` as claims | The record answers "which provider fills each slot" with citations |
| T5 | Morphogen bootstrap: OTel observer, anomaly, planner with predictions, intent actuator, prediction verifier, lane policy | One full loop on Morphogen's own stack |
| T6 | G2 | As above |
