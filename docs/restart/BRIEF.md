# Restart brief: Morphogen as the local morphological drive

Written 2026-11-04, when this repository was frozen. It is the starting point for a new
project, not a plan for this one. Read [LESSONS.md](LESSONS.md) alongside it.

## What it is

In development, cells do not consult a blueprint. Each reads a morphogen's concentration where
it sits and responds; the shape emerges from many local responses. Morphogen is that drive for
software and agent systems. At each point it is given, it picks an optimizer and a measure,
runs the search behind a judge the search cannot edit, and proposes the change with its
evidence.

Many tools already optimize things, and some already measure and judge. Morphogen does little
on its own: it integrates the right piece at the right point, and owns the search over those
choices.

It is one subsystem of a larger cognitive framework, operable alone:

| Piece | Job | Relation to Morphogen |
|---|---|---|
| **Mapper** | builds representations: the intent map (as tests), the observed map, catalogs | produces the points Morphogen works on; reads Morphogen's evidence back |
| **Builder** | builds from the intent, fixes, upgrades, instruments (ordinary Claude Code) | makes red tests green; assembles candidates |
| **Morphogen** | changes a system locally, point by point, against a judge it cannot edit | this project |
| **Deploy** | the target's own release process | applies what the operator promotes; what it observes comes back as evidence |

## Precedents

- **Reconciliation.** A Kubernetes object has a `spec` (intended) and a `status` (observed), and
  a controller reconciles them. That is the intent map, the observed map and the builder.
- **Local drives.** The Horizontal Pod Autoscaler attaches to one target, reads metrics, and
  changes one setting within `minReplicas` and `maxReplicas`, bounds the operator owns. Morphogen
  generalizes it: any point, any modality, structural changes too, behind a judge built for
  agent-written candidates.
- **Judges for deployments.** Kayenta (Netflix and Google) compares canary with baseline using a
  Mann-Whitney U test; a metric fails when its 98% confidence interval lies outside a tolerance
  band; scores roll up to 0-100; judges are pluggable, and metric collection is not the judge's
  job. Argo Rollouts calls Kayenta or its own Prometheus analysis to promote or roll back. These
  resist cheating only because metrics are collected outside the code.
- **What nobody does:** judge an agent-written candidate before it ships, assuming the candidate
  will try to cheat. No protected evaluator, held-out cases, red team or parameter ownership in
  any optimizer or canary tool read (GEPA, OpenEvolve, AFlow, Kayenta, Argo Rollouts).

## Value claims and how to test them

Little here is new as invention. Each piece has prior art: TDD, behaviour-driven development and
requirements traceability (safety-critical standards such as DO-178C trace tests to
requirements); algorithm selection and AutoML portfolios; canary analysis; held-out tests;
reconciliation and reflexion models. Two claims carry the project:

1. **Built for an improver that cheats.** The improver is an agent that games whatever it can
   reach, and every interface assumes so: tests owned by the intent, evaluators out of the
   candidate's reach, held-out cases, enforced parameter ownership, outside-only measurement, a
   red team as the judge's regression suite. Each exists somewhere; none of the tools read
   combines them (optimizers trust their evaluator; canary tools trust outside collection and
   ignore the candidate's author; coding agents can edit their tests). The Darwin Gödel Machine
   result is the evidence that instructions alone do not hold.
2. **Point by point beats whole-system.** Improving a system at points, with an optimizer chosen
   per point and neighbour checks, does better than one optimizer on the whole system.
   **Unproven**, and possibly false: GEPA already evolves several components together, and an
   agent given the whole repository may match it.

The test, same system and same budget, comparing improvement on held-out cases and the rate of
cheats that get through:

| Arm | Setup |
|---|---|
| A | GEPA, or Claude Code, on the whole system, with its own evaluator |
| B | the same, behind Morphogen's gate only |
| C | full Morphogen: points, selector, gate |

B over A means the gate is the value. C over B means the selector adds something. If C does not
beat B, Morphogen is the gate plus adapters, and the selector is cut.

## Test-driven, end to end

The intent map is an executable spec, and the three roles follow red, green, refactor:

| Step | Two-map view | Who |
|---|---|---|
| **Red** | the intent declares an interface, connection or behaviour; its test fails (an absence) | the mapper, writing intent as tests |
| **Green** | the observed system passes | the builder |
| **Refactor** | parameters or shape change while every test stays green and a measure improves | Morphogen, behind the judge |

Intent becomes tests at every scale:

- a slot's interface: unit and acceptance tests any filling must pass;
- a connection between slots: contract tests at the boundary (consumer-driven contracts, as Pact does);
- a requirement with a reason: the reason says why the test exists and when to change it;
- system-level intent (latency, error rate, cost): service-level objectives on telemetry observed
  from outside.

Rules that follow:

1. **Tests belong to the intent, not to the builder.** An agent that writes both code and tests
   can pass by weakening the tests ("delete the tests" is already a red-team cheat). The mapper
   or the operator owns them; the builder and Morphogen read them only.
2. **Some cases are held out.** A builder or optimizer that sees every test builds to the tests.
   The judge keeps cases back.
3. **Intent coverage, not code coverage.** The mapper reports which intent claims have a test and
   which are only stated. Purpose and design reasons stay as notes.
4. **Tests are the drift check.** Intent changes turn tests red (the builder's work); code drift
   shows as divergence in the observed map (the mapper's question).

## Parts

| Part | Job | Written or integrated |
|---|---|---|
| **Spec** | desired state per point: location, modality, interface tests, parameters with owners and bounds, neighbours, measures, held-out cases | written: the format |
| **Selector** | the search over (point × optimizer × measure): modality narrows it, evidence from past runs updates it | written: where Morphogen sits |
| **Optimizer adapters** | hand a point and an inner evaluator to GEPA, Optuna, OpenEvolve, AFlow or a Claude Code worker | integrated |
| **Measurement adapters** | the judge's runner offline; OpenTelemetry, its eBPF instrumentation (OBI) and Prometheus live; each point's harness | integrated |
| **Gate** | offline at each point: protected test setup, held-out cases, owners enforced, neighbour tests, red team. At system scale: canary against a baseline | offline gate written; system scale integrated (Kayenta-style) |
| **Apply and observe adapters** | turn a promoted change into a branch, PR or deploy; read status back | integrated (git, Argo, Terraform, ...) |
| **Map adapters** | read points from Backstage, an indexer, or a hand-written spec | integrated |
| **Evidence ledger** | every trial, verdict and observation as claims with trust classes | written, or a store |
| **Loop** | observe → pick a point → optimize → gate → propose → (operator) → apply → observe | written: small |

## Measurement rule

Telemetry a program emits from its own SDK is written by the candidate: it can inform a decision,
never make one (the `reported.*` rule in this repo). Telemetry observed from outside the process
can decide: the judge's own wrapper offline; OBI live, which captures traces, request rate,
errors, duration and service relationships from the executable and network without code changes
(Linux, kernel 5.8 or later).

## The gate at two scales

- **Point, offline, before merge.** Inner evaluator for the search: cheap, outside the optimizer's
  reach, not statistical. Then the judge, once, on the optimizer's best, with paired statistics,
  on held-out cases, with the neighbours' interface tests. Catches cheating and overfitting.
- **System, online, after apply.** Canary against a fresh baseline running the production version
  (Google's guidance), on outside-observed telemetry. Catches interactions, load and emergent
  regressions. A change that passes at the point and fails here is rolled back, and the selector
  learns from it.

## The spec format (draft)

```yaml
points:
  retrieval-prompt:
    at: agent/prompts/retrieve.md        # a file, file#symbol, or a marked block
    modality: text                       # text | code | numeric | workflow | ...
    interface:                           # owned by the intent; read-only to builder and optimizer
      check: python -m pytest -q tests/test_retrieve.py
      contracts: [contracts/answer-prompt.json]   # tests at the boundaries with neighbours
    parameters:                          # the #58 format, unchanged
      top_k: {file: agent/config.yaml, key: retrieve.top_k, owner: agent, range: [1, 50]}
      model: {file: agent/config.yaml, key: llm.model, owner: operator}
    neighbours: [answer-prompt, memory-store]
    measure: targets/qa                  # a directory with target.yaml: harness and metrics
    cases: {search: cases/search, holdout: cases/holdout}   # holdout is read by the judge only
    alternatives: catalog/retrieval      # optional: where candidate fillings come from
```

A mapper writes it, or a person does by hand. Morphogen reads it and nothing else about the system.

## Optimizer catalogue (first entries)

| Modality | Optimizer | Licence | From the source (read 2026-11-04) |
|---|---|---|---|
| text, DSPy programs | GEPA 0.1.4 | MIT | candidate is a dict of named texts; one component per round or all; merge of Pareto candidates; DSPy adapter changes signatures, modules and control flow; evaluator isolation is the user's (in-process or subprocess helper) |
| marked code blocks | OpenEvolve 0.4.1 | Apache-2.0 | evaluator file imported into OpenEvolve's own process; timeouts and retries, no sandbox |
| workflow graphs | AFlow | not checked | Monte Carlo tree search over workflows as code; evaluator not read |
| numeric settings | Optuna | not checked | not yet read |
| anything, by an agent | Claude Code workers with strategy cards | ours | what this repo does today |

## First milestone

One prompt point, GEPA as its optimizer, end to end:

1. Red team first: a candidate that reads or edits the inner evaluator, the interface tests or
   the held-out cases is refused.
2. GEPA improves the inner score.
3. The judge on held-out cases accepts a real improvement and refuses an overfit one.
4. The verdict records the optimizer and the parameter values as evidence.

Then: a numeric point with Optuna; a structural change gated by a neighbour's contract test;
then the three-arm comparison above, on a system with at least two points, before building more
of the selector. One live point gated by a canary on OBI telemetry comes after that.

## Packaging

The core is a controller: a library and a CLI, with an MCP server so agents can drive it. A
Claude Code plugin or skill folder wraps it (Agent Skills format; an optional
`.claude-plugin/plugin.json` adds agents, hooks and MCP servers, loaded as `<name>@skills-dir`).
Subagents shipped inside a plugin ignore `mcpServers` and `hooks`. On Kubernetes the same core
could run as an operator with a `Point` resource. Checked against code.claude.com/docs on
2026-11-04.

## Carry over, drop

| Carry over | Drop (or hand to the mapper) |
|---|---|
| judge: statistics, overlay of the test setup, parameter reading, probes | lists, maps, mounting, catalogs, the self-map |
| runners (Docker, Podman, none) | map, onboard and playbook skills; the explorer agent |
| the red team, every cheat | knowledge-system and role slots |
| the evidence log and trust classes | the admin UI |
| `documents.load` with a schema per document | most of the 19 MCP tools: keep judge, measure, evidence |
| the worker and reviewer agents | |
| evals with and without; the eval-loop CI job | |

## Open questions

- Running neighbours' contract tests without the judge's cost multiplying per point.
- Where held-out cases live so no candidate can read them: outside the container, or only in the
  judge's process.
- Learned-state reset between trials for stateful targets such as an agent's memory (#45).
- Token cost observed from outside, through a model gateway (#43).
- How the selector learns: a lookup by modality plus evidence, or a bandit over
  (point × optimizer).
- Not read yet: Optuna; AFlow's evaluator; Pact; Argo Rollouts' official analysis docs (the
  field names seen were in tutorials); the scip-python and scip-typescript licences.

## Research this rests on

- Mapping: Backstage system model, relations and descriptor format (the API kind holds
  `spec.definition`); C4 and the Structurizr DSL; CycloneDX 1.6 (component `evidence` with
  `confidence` and `methods`, `dependencies` with `provides`, signed `annotations`); SCIP
  (Apache-2.0); codebase-memory-mcp (MIT, v0.12.1; links environment variables and config keys
  to code by name, not values); software reflexion models (Murphy, Notkin, Sullivan, FSE 1995:
  convergences, divergences and absences between an intent model and the source).
- Optimizers: GEPA (arXiv 2507.19457), OpenEvolve, AFlow (arXiv 2410.10762), Darwin Gödel Machine
  (arXiv 2505.22954; an agent removed the logging its hallucination check relied on, despite
  instructions not to).
- Judging and measuring: Kayenta and Spinnaker's canary judge docs; Google and Waze on canary
  baselines; Argo Rollouts analysis (tutorials); OpenTelemetry eBPF Instrumentation docs.
- Parameter ownership: no standard found. flagd has free-form `metadata` only; Atlas has
  ownership rules for database schema objects.
