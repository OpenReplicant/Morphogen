# Rebuild 5: kernel and Morphogen carry-over map

Started from the "Rebuild 5: Kernel and Morphogen Carry-Over Map" doc (Oct 23, 2026); the tables now say what was
built. Rebuild 5 keeps the
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
| `ontology/slots.yaml` (42 slots) | Rewrite as the self-blueprint | Done: `kernel/blueprint/slots.yaml` and `morphogen/distribution.yaml`; the original is in rebuild 4's repository |
| `ontology` packs | Port; RDF at the edges | Ported: `kernel/packs/`, loaded by `kernel/providers/pack-loader` (T4) |
| `shapes/` (SHACL) | Rewrite as one validator provider | Done: `kernel/providers/validator-shacl` (R5-11, R5-15) |
| `kk` command | Rewrite, smaller | Replaced: `morphogen/deploy/local.py` and the container image (R5-38, R5-39) |
| `docs/LESSONS.md` | Port whole | Ported, then cut to what this rebuild's tools need (lessons about RuleGo, PostgREST, `kk`, AGE stay in rebuild 4) |
| `docs/decisions.md` (D-01 to D-93) | Keep as history | Settled unless superseded; referenced from `docs/decisions.md` |
| `parked/` | Drop | — |

### Modules

| Module (rebuild 4) | Verdict | Where it is now |
| --- | --- | --- |
| kernel-mcp | Port | `kernel/providers/kernel-mcp` (agent-interface slot, R5-13) |
| validator-shacl | Rewrite | `kernel/providers/validator-shacl` (the validator's default, R5-15) |
| belief-corroboration, verifier-quotes | Port | `kernel/providers/` (R5-11, R5-13) |
| truth-maintenance | Parked (R5-12), then ported | `kernel/providers/truth-maintenance` (T18, R5-31) |
| kernel-mcp briefing | Park: its slot stays unfilled (R5-12) | — |
| recall-index, recall-dense | Port BM25; dense not ported (R5-13), re-ranking in `kk.recall` (R5-35) | `kernel/providers/recall-bm25` |
| evaluator | Port, central | `kernel/providers/evaluator` |
| self-encoder | Rewrite | `kernel/providers/self-encoder` (blueprint, providers, distribution files; R5-14, R5-27) |
| ingest-filter-gitleaks, pack-loader | Port | `kernel/providers/filter-gitleaks`, `pack-loader` |
| encoder-interaction, skill-interview, map-gaps | Port, for systems rather than organisations (R5-29) | `morphogen/modules/interview-encoder`, `map-gaps`, `morphogen/skills/interview` |
| observer-prometheus, anomaly | Port; add an OTel observer | `morphogen/modules/observer-prometheus`, `observer-otel`, `anomaly` |
| skill-adaptation-planning | Rewrite: predictions and risk class | `morphogen/modules/planner` (deterministic, R5-20) |
| actuator-compose | Rewrite: intent actuator | `morphogen/modules/intent-actuator`; running is the runtime slot's (`runtime-compose`, `runtime-quadlet`) |
| ui, view-modules | Rewrite | `morphogen/ui/` (T21); the window manager of views is R5-O14 |
| encoder-eventlog, encoder-bpmn, conformance, learner-process, view-bpm, view-devops | Park | Parked; R5-O17 would port them as encoders and processes (R5-O18) |
| encoder-papers, memory-extractor | Park; evals stay as baselines | — |

### Evals

| Eval | Verdict |
| --- | --- |
| validator, belief-v0 | Into the conformance suite |
| self-model questions | Port; the self-modifying gate builds on it. **Ported** (T11, R5-27): G7 passes on both sets with Haiku (kernel 11/12, Morphogen 12/12, under a stricter grader); the kernel set is one short of rebuild 4's 12/12 |
| SciFact, LongMemEval, RCAEval | Port as baselines the new build must match |
| BPI Challenge 2019 | Park; the first floor of R5-O17 |

## Morphogen, the only distribution

### Bootstrap set

A system that builds systems cannot build its own first parts. These ship in place; everything after them
arrives through the loop.

| Slot | Bootstrap provider | Now |
| --- | --- | --- |
| Record store and write pipeline | Postgres claims, change sets, lanes | `record-postgres` |
| Conformance suite | Invariant tests | `kernel/contract/` (G1) |
| Design agent | Interview and blueprint encoder, map gaps | `interview-encoder`, `map-gaps`, `design-blueprint`, `encoder-compose` |
| Monitor | OTel observer, Prometheus observer | `observer-otel`, `observer-prometheus` |
| Analyse | Anomaly detection, watchers on the change feed | `anomaly` |
| Plan | Planning skill with predictions and risk class | `planner`, `builder` |
| Review lane | Autonomy level × risk class | `lane-autonomy` |
| Execute | Intent actuator: commits to git, orchestrators reconcile | `intent-actuator`, `deploy/reconcile.py`, the runtime slot |
| Verify | Separate verifier compares observations with predictions | `prediction-verifier` |
| Evaluator | Scores a candidate against the incumbent | `evaluator`, `sandbox` (G2) |
| Catalog lookup | Configured registries, matched on slot requirements | `registry-lookup` |
| Recall and MCP | BM25 recall, kernel MCP | `recall-bm25`, `kernel-mcp` |

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
| T3 | Port kernel-mcp, recall-bm25, belief-corroboration, verifier-quotes, evaluator into `kernel/providers/` against `kk.interfaces` | Each module's tests; recall matches rebuild 4 on SciFact. **Done** (R5-13): `kernel/providers/test.py` 5/5; SciFact nDCG@10 0.6606 ≥ 0.6594 |
| T4 | Rewrite the self-encoder: encode `kernel/blueprint/slots.yaml` and `morphogen/distribution.yaml` as claims | The record answers "which provider fills each slot" with citations. **Done** (R5-14): `self-encoder/tests/test_self.py` answers all 16 kernel slots from the manifests, each part cited to its file and line |
| T5 | Morphogen bootstrap: OTel observer, anomaly, planner with predictions, intent actuator, prediction verifier, lane policy | One full loop on Morphogen's own stack. **Done** (R5-20): `morphogen/tests/test_loop.py` takes the belief model's feed lag over its limit through plan, a person's approval, an intent commit and a restart, to a verdict that the prediction held, each step citing the one before |
| T6 | G2, test-first (R5-21): T6a every slot declares its contract; T6b sandbox and evaluator comparison; T6c builder; T6d replace-provider through plan, actuator and reconciler; T6e the end-to-end G2 test and a recorded gate run | As above. T6a **done**: every kernel and Morphogen slot names its contract; the analyser has a case set (11 cases, 7 mutants). T6b **done**: `sandbox` measures a candidate and the incumbent on a copy of the record; the evaluator records both, linked to their providers. T6c **done**: `builder` turns a build request into a committed experiment with a candidate (fixture or agent-harness strategy), recorded as claims citing the request. T6d **done**: the planner turns a step-time anomaly into a build request and a measured, better candidate into a replace plan; the intent actuator and the reconciler run the candidate. T6e **done**: `morphogen/tests/test_g2.py` passes (the analyser replaced by a faster candidate it asked for, measured, a person approved, observed within the prediction), and the recorded gate run with a candidate Haiku built passed (`morphogen/evals/g2/runs/2026-10-23-haiku`). Review fixes (R5-22): the slot owns its contract runner, model-built code runs only as the incumbent's own login with no other credentials, approval names the candidate's content hash. Open before any level above L1: step times measured from outside the provider, a token per service, a service-level analyser case set |
| T7 | Close R5-22's open items before going further (R5-23): the sandbox times full passes from outside the provider; service-level case sets (every case through one real pass); a telemetry token per service; the gate run again | `test_sandbox.py` (a candidate that reads only part of the record fails the service cases), `test_observe.py` (one service's token cannot report as another), `test_g2.py`, and a recorded gate run. **Done**: G2 passes under the new checks; the gate run's Haiku candidate made a real full-pass gain (0.087 s against 0.131 s) and passed, but with a bug the cases missed, now case 12 (`morphogen/evals/g2/runs/2026-10-24-haiku`). Review fixes (R5-23 (f)): benchmark outputs must equal the incumbent's (`agreement`), only applied change sets count, nothing a provider starts outlives its run |
| T8 | Confine model-written code at the OS level (R5-23 (f)): candidates and harness builds run as an OS user of their own (or a container) against a cluster that asks every login for its password; a two-pass service case (retraction, superseded limit) | `test_sandbox.py`: a candidate cannot read its parent's environment, connect as another role, or keep flagging a retracted observation. **Done** (R5-24): candidates and harness builds run as a run user leased per run, from root-owned copies, refused while the cluster lets any login in without a password; sandbox candidates get a login of their own that reaches no other database; every process of the run user ends after each run; case 13 (two passes); a candidate that keeps what it read fails it. Open: the network, and a sandbox cluster of its own |
| T9 | G3, test-first (R5-25): a small real system Morphogen did not build (podinfo 6.9.2 frontend and backend with Redis, pinned by digest) described by an operator's compose file in `intent/systems/podinfo/`. T9a the map: `encoder-compose` records services, images, settings and who connects to whom, each citing its compose line; T9b `observer-prometheus` records each service's request time from its metrics; T9c the planner follows the map from the anomalous service to the one whose setting answers it, and the intent actuator edits that service's environment in the compose file; T9d `deploy/compose.py` runs only committed compose files that pass an allow list; T9e `morphogen/tests/test_g3.py` and CI | `test_g3.py`: the frontend's request time over a person's limit becomes a plan on the backend's delay setting that cites the map, a person approves, the actuator commits, the stack is reconciled, and the verifier finds the prediction held; every step cites the one before. **Done**: `test_g3.py` passes: the frontend's request time (0.29 s against a 0.15 s limit) became a plan on the backend's `PODINFO_RANDOM_DELAY_MAX` (600 to 155) citing the map's connection, a person approved it, the actuator committed it, `compose.py` applied it, and the verifier found the prediction held (0.08 s in the three windows after). Open: map gaps, mapping what runs (`docker inspect`), a login of its own for encoder-compose |
| T10 | Close R5-24's open items (R5-26): T10a a confined run reaches over the network only the addresses its lease allows (an nftables chain per run user); T10b the sandbox measures provider code on a cluster of its own, never the record's | `test_sandbox.py` (a confined run reaches the allowed port and no other, nothing after its lease; the sandbox refuses without its own cluster or on the record's), `test_build.py` (the harness reaches only `KK_BUILDER_NET`), G2 and G3 under the new checks. **Done**: 15/15 module tests with the fence and a second cluster. Open: relays over Unix sockets (name lookups), a ruleset flushed mid-run; a network namespace per run would close both |
| T11 | Port the self-model questions (rebuild 4 eval/self-model, G7): the self-encoder records a distribution's own providers (`scan --providers DIR`); `kernel/evals/self-model` (12 questions on the kernel's blueprint and providers, the reference agent, the grader, a Claude Code agent over the kernel MCP server) and `morphogen/evals/self-model` (12 on Morphogen's providers, its distribution and the podinfo map) | The reference agent passes both sets in CI; `test_grade.py` (each broken answer fails, two wrong of twelve fail the gate); a recorded live run against rebuild 4's floor (12/12). **Done**: G7 passes with Haiku over MCP: Morphogen 12/12; kernel 11/12 in two runs (`runs/2026-10-24-claude-code-haiku*.json`): on the one question whose provider and slot share a name (evaluator) Haiku spliced two claim ids into one that does not resolve. Open: the kernel set at the floor |
| T12 | Port RCAEval (rebuild 4 eval/rcaeval, R5-28): `morphogen/evals/rcaeval/run.py` runs RCAEval's pinned main.py with the analyser's own statistic, rebuild 4's statistic and BARO; RE1 to choose, RE2-OB and RE2-TT held out | The analyser at rebuild 4's floor; every statistic tried recorded (`EXPERIMENTS.md`). **Ported, open on RE1**: the analyser missed metrics flat before a fault (no score without spread); it now scales a flat history as rebuild 4's statistic did (case 14, 3 mutants). Held out, above the floor: RE2-OB 0.942 (0.930 before; floor 0.935), RE2-TT 0.773 (unchanged; floor 0.643 on 63 of 90 cases). RE1 0.874 / 0.914 / 0.788 against 0.894 / 0.922 / 0.800: under, because after a fault the analyser's history holds faulty windows |
| T13 | The design agent (R5-29), test-first: T13a the intake filter (kernel slot, gitleaks, rebuild 4 ingest-filter-gitleaks); T13b `interview-encoder` (rebuild 4 encoder-interaction: each message an `as:Note` the interviewer quotes); T13c `map-gaps` for systems, with a case set (a service with no image, a connection to a service not on the map, a service with no documented limit, a service nothing connects to); T13d the interview skill for systems (the person's words as TOSCA map claims quoting their messages, then questions from the gaps); T13e from description to intent: a map with no gaps becomes a compose file a person approves, the intent actuator commits it, and encoder-compose's map of it equals the described one | `morphogen/tests/test_design.py` (a scripted interview closes the gaps it asks about and ends with the expected map and an approved compose file whose encoded map matches; every claim quotes its message and the quote verifier supports it); a recorded run with Haiku as the interviewer. **Done**: 19/19 module tests with `test_design.py`; gap-finder 12 cases, 11 mutants; Haiku as the interviewer passed runs 4 and 5 on a skill whose example is not the eval's (run 1 failed for want of an example; runs 2 and 3 used an example that overlapped the eval and are not counted; `morphogen/evals/design/runs`). Open: running a new system, a live interview |
| T14 | Catalog lookup (R5-30): catalogs as open component sets of any kind (a `kkt:Profile` and its entries, `dcterms:isPartOf` it), adapters by kind (`components`, `pypi`, `providers`), rules and search as toggles; a build request is answered from provider catalogs too, a pinned provider entry becoming a sandbox candidate | `registry-lookup` tests: a non-software component set and a software one searched alike, each entry recorded with its rules' verdicts, an enforced rule withholding only the offer; PyPI-shaped JSON from a local server; a provider catalog at a pinned commit answers a build request, its candidate committed as an experiment the sandbox picks up, a later commit not taken |
| T18 | Truth maintenance (R5-O7 a1; kernel slot `truth-maintenance`, default none until now): port rebuild 4's module (D-89) as a feed consumer; when a premise of an inferred claim is refuted, superseded or retracted, the inferred claim is flagged for re-derivation and its belief capped; its output re-enters at intake. Inferred claims whose premises change now exist: catalog `kkt:fulfills` offers (T14) and answered gaps (T13) | Retracting a build request's claim flags the offers inferred from it, naming the premise, and leaves the offers to other requests alone; chains are followed; the belief model caps flagged claims at 0.25; restored premises restore them, a second withdrawal flags them again; a superseded premise undermines what was built on it, even with the same value (R5-31); a redacted premise too; verdicts go to the claim's own scope; 6 mutants (never flags, never restores, chain not followed, redaction ignored, one scope for all, re-flag returns the first change set) fail its tests; the kernel contract still passes. **Done** (`kernel/providers/truth-maintenance`; registry-lookup's service test) |
| T19 | Dependency reasoning over the map (R5-O7 a2): the transitive closure of `kkt:dependsOn` (`connectsTo`, `hostedOn` as its subproperties) as a library both the planner and the analyser read; the `blast_radius_budget_slots` guard in `autonomy.yaml` implemented with it; the analyser orders root-cause candidates by the map (a service whose dependencies are healthy ranks above one whose dependencies are not) | A plan whose reach exceeds the budget is refused before review; on RCAEval RE1 (train, D-64) the map-aware ordering is measured against the T12 numbers, kept only if it does not fall below them on dev. **Done** (R5-32): `kk.graph`; the planner refuses a plan from an anomaly over the budget before review, failing closed (`planner/tests/test_service.py`, 6 mutants); the analyser does not read it (below); the map-aware ordering fell below the analyser on RE1-OB under every rule (best 0.864 against 0.874), so it was not kept and RE2 was not used |
| T20 | Requirement matching in catalogs (R5-O7 a3): a need states requirements (`kkt:propertyValue` named, with a comparison: equal, at least, at most, one of, SPDX allowed), an entry's properties are checked against each, deterministically; `kkt:fulfills` is inferred only when every requirement holds, `derived_from` the requirement and property claims; word search stays for people | A Python package needing `requires_python` ≥ 3.12 and an M8 stainless bolt are matched and mismatched alike; an entry missing a required property is not offered; mutants fail. **Done** (R5-33): `registry_lookup/requirements.py` and `match_needs` over the record; `kkt:constraint` in kk-tosca 0.4.0; values per catalog; 14 mutants fail its tests |
| T15 | Feed consumers keep their cursor (R5-O5): watchers that must act once per change (anomaly, prediction verifier) survive a restart without acting twice | `anomaly/tests/test_service.py`: down while a spike and 4 windows after it arrive, the service finds the spike on start; a restart with nothing new starts no run; a crash between submit and finish leaves the cursor and submits nothing twice; beliefs on older windows start no run; 8 mutants fail; G2 still passes. **Done** (R5-34): `kk.lib.resume` and `feed_since`; the anomaly service judges each change set's latest windows from its durable cursor; the prediction verifier needs none (every open prediction each pass, verdicts keyed by prediction); G2's fixture candidate rebuilt on the new incumbent, and the planner's prediction scaled from the latest observation |
| T16 | Port LongMemEval (kernel recall; rebuild 4 0.10 → 0.62 with a 2.6B reader); then the kernel's open items (R5-O3, R5-O4, since answered by R5-16 and R5-17), a network namespace per run, the kernel self-model at 12/12, the RCAEval RE1 gap; the UI after the design agent, when the owner says | T16a, retrieval (R5-35): `kernel/evals/longmemeval/run.py` on the same 100 questions (93 with evidence) at rebuild 4's floor: BM25 session R_any@5 0.935 (0.935), NDCG@5 0.866 (0.866), R_all@5 0.806 (0.817); with cross-encoder re-ranking in `kk.recall` and kernel-mcp's `search` (KK_RERANK=1) 0.968 (0.968), NDCG@5 0.921 (0.923), R_all@5 0.914 (0.925), R_any@10 1.000 (1.000). End to end with the 2.6B reader (R5-35 (d)): 0.624 against rebuild 4's 0.683 in the same mode, judge and retrieval ruled out; the free reader cannot be pinned. Open: the end-to-end floor, with a pinned reader. The rest of the row (a network namespace per run, the kernel self-model at 12/12, the RCAEval RE1 gap) is parked: the owner chose Morphogen's use case and a UI over more kernel work (Oct 2026); T21 is next |
| T17 | Forge module (R5-O6 c2 to c5, if accepted): a plan in the review lane opened as a PR showing exactly what the actuator would write; a mapped person's approving review relayed as `api.review` under their own reviewer role, for the risk classes policy allows (never irreversible), voided by any push; candidates published as branches; forge CI as one more verifier at intake; reconcilers pull intent from the forge, Actions never deploy | An approval through a PR applies only for a mapped reviewer, an allowed risk class and the current head; a push, an unmapped login or an irreversible step is refused. Proposed (R5-O6) |
| T21 | Review and loop UI (owner, Oct 2026: focus on Morphogen and a UI, not the kernel; rebuild 4 `ui` and `view-modules`, rewritten): a small web UI over the loop: the review lane (each plan with its citations, belief, prediction and risk, approved or refused by a person signed in as themselves), the managed systems and their maps, anomalies, predictions and verdicts | `morphogen/tests/test_ui.py` (a server process and headless Chromium): a plan waiting in the review lane shows its label, risk, step and prediction and every claim it cites with its belief; a person signed in with their own login approves it and the store records it under their role; the loop lists the anomaly; the systems view draws the map; a wrong password, a login that is not a person's, a person who is not a reviewer and a call without a token are refused. **Done** (R5-36): `morphogen/ui/` (serve.py, people.py, web/); a sign-in that skips the reviewer check fails the test. T21b **done**: the loop shows each plan with who decided it, the run that carried it out and by whom, and its verdict, which opens its lineage (`test_ui.py`, 3 mutants fail it) |
| T22 | Close the design loop (owner, Oct 2026: before running Morphogen on their own machine): a described system ends running, not at a file | `test_compose.py`: with `--all`, a system committed later starts and an uncommitted one does not; `test_design.py`: an image named by tag is asked to be pinned before anything is proposed; `test_blueprint.py`: a file the compose runner would refuse is not proposed; gap-finder 13 cases, 13 mutants. **Done** (R5-37) |
| T23 | Morphogen on a machine of your own (owner, Oct 2026): one command brings up the record, the services, the compose runner and the UI | `morphogen/tests/test_local.py`: from `up` to a described system running and `down`, on a throwaway instance. **Done** (R5-38): `morphogen/deploy/local.py`, `morphogen/deploy/LOCAL.md` |
| T24 | Morphogen as a container image (owner, Oct 2026: ship an image, keep the bare-metal way; Claude Code signs in inside the container by default, the host's `~/.claude` read-only or shared by choice): the record, the services, the UI, the compose runner and Claude Code in one image, each part a user of its own | `morphogen/tests/test_container.py`: the image built from its pinned Containerfile runs the whole T23 path, and Claude Code, run as its own user, can read neither the instance's secrets, nor the socket, nor a service's environment, nor more of the host's `~/.claude` than its login unless shared on purpose, while no service reads its login. **Done** (R5-39): `morphogen/deploy/container/Containerfile`, `morphogen/deploy/container.py`; `local.py` gains embedded Postgres, `up --foreground` and `claude`; the UI now listens on 127.0.0.1 as documented; pins are exact and hashed, the two-week rule dropped (R5-41). Passes under Docker and rootless Podman. Open: a published image, arm64 built and run, the compose runner checking files against approved plans (done, R5-44), the token (R5-O10), the runtime slot (R5-O9; begun, R5-44) |
| T25 | The kernel made extractable (R5-42 (b)): a shared case set for each kernel slot that has only its provider's own tests; the wire API versioned; the blueprint matching what runs; the durable cursor out of `kernel.run.cost` | Each new case set passes on its default provider and fails under its mutants; `kernel/contract/run.py` refuses a filled slot whose contract is `provider-tests`; the cursor survives a run whose cost names `feed_seq`. Done (R5-43): 9 new case sets, 69 cases, each passing on its default provider; 80 kernel mutants killed (lane-autonomy's 3 by the lane-policy set); the verifier set found verifier-quotes picking up its own claims, fixed; `api.py check` holds the API at 1.0.0; `kernel.run.feed_seq`; `harness-adapter` unfilled |
| T26 | The compose runner runs only what an approved plan names (R5-39 open item): a file committed to the intent repository by anything but the intent actuator carrying an approved plan's content hash is refused | `test_compose.py`: a file committed by another process, or edited after approval, does not run; an approved one does. Done (R5-44): the rule is the runtime case set's (unapproved, awaiting, edited, work tree, rollback, other system, clearance); an adopt step for a file a person brought in; G3 approves podinfo before it runs |
| T27 | The runtime slot (R5-O9 as amended by R5-42 (c), no Score): `compose.py` becomes its first provider behind a case set every runtime passes; then Podman Quadlet, then K3s; an encoder for what actually runs | The runtime case set (a committed file runs, an uncommitted one does not, a file outside the allow list is refused, a removed system stops) on compose, then Quadlet. In progress (R5-44): the slot, its 16 cases on a stub engine and runtime-compose (11 mutants) are done; a removed system is left running (R5-25). Quadlet done (R5-46): `runtime-quadlet` passes the same cases (17 after its review), the loop shared as `morphogen.runtime`; K3s, an encoder for what runs and the UI's diff for node steps to do |
| T28 | Resources and costs (R5-O12), with generic actions over documented settings, scale, image version and resource limits | To be written test-first when started |
| T29 | Overlapping vocabularies and ontology catalogs (R5-O13): query-time mappings, SSSOM import, a `vocab` catalog adapter | To be written test-first when started |
| T30 | R5-47's foundations: the prepared-query cache in `kk` for every SHACL user; the validator refusing only `sh:Violation`; `emits` and `consumes` in every provider.yaml, checked against the packs, recorded by the self-encoder, and a selection's closure | `kernel/providers/tests/test_terms.py` and `morphogen/tests/test_closure.py` fail on an unknown term, an undeclared manifest and an unmet need (without an observer, without the planner); the validator's `test_severity.py`; the self-encoder's `dependency-lines` case. Done (R5-47) |
| T31 | The gap-finder slot moves to the kernel (R5-47): its case set to `kernel/contract/slots/gap-finder`, the shape-driven finder its default provider with a feed service writing gaps, the kk-tosca shapes installed with their pack | The gap-finder cases on the kernel's provider; the design agent's loop (`test_design.py`) on the new finder, design-blueprint reading the gaps of whichever provider fills the slot (today only map-gaps'); map-gaps passes the same cases until retired |
| T32 | A drift slot (R5-O18 (6)) and T27's encoder of what runs: claims about one component as intended, described and actual, compared term by term; the first actual-state source a container engine's list of what runs | To be written test-first when started |
