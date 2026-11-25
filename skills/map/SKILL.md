---
name: map
description: Map a system - what it is made of, the role each part plays, the interfaces that make parts interchangeable and the cells a judge can measure - as Backstage catalog entity files with evidence, or start a project that has no map. Use when the user asks to map, model or inventory a system (software or not: a codebase, a team, a process), asks what something is made of or what could be swapped, wants to start Morphogen on a project with no map, hands over a system for a builder agent to create or change, or before cataloguing options for a part (the catalog skill).
---

# Mapping a system

The map says what the system is made of, the role each part plays, what each part promises and what may be
changed and judged. It is **files**: Backstage catalog entities in the project, written by you, read by the
judge from the base commit. No database and no server are needed, and any Backstage UI can load the same files.
A map counts for a verdict only once the operator has approved it and it is on main. Your job is a draft the
operator can approve: small, checked, every claim traceable to where you found it.

The cell rules are part of the same files: `spec.morphogen` on the entity a cell judges (schema:
`schemas/morphogen-spec.v1.json`; section 1 shows where each kind of rule goes). There is no other
project file for the judge to read.

## 0. How you work

- **Interview a person** when there is one: what the map is for, what might change, what should get better.
  Ask before searching for what only they know; ask last, with what you found in hand, for what the system
  cannot tell you.
- **Hypothetical design work** when the thing does not exist yet, or a change to it is only proposed: map the
  design as intended. Mark such an entity `spec.lifecycle: experimental` and say in its description that it is
  not built; an intended part with no source is the intent, not a finding.
- **Find facts** through whatever the harness reaches: read files and run commands; call any MCP server you are
  given (a documentation server, a ticket system, a repository host); search the web. Use the harness's own
  tools by the names it gives them.
- **Build out iteratively.** Map the whole coarsely first, then take one part at a time and detail its
  sub-structure when the operator's goal needs it (a part nobody would change needs no parts of its own).
  Write after each pass, so the map is always valid and reviewable.
- **Evidence for each claim.** See section 3.

## 1. What a map is

The map is a **Backstage catalog**: entity files (`catalog-info.yaml`, or a `catalog/` folder of them, tied
together with `Location` entities), as many files as the project likes. Morphogen already reads them with no
Backstage server.

| A thing in the map | The entity |
| --- | --- |
| a whole, a product, a process | `System` (nest with `Domain`, or `spec.system`) |
| a part | `Component`, with `spec.type`, `spec.lifecycle`, `spec.owner`, `spec.system` |
| a part inside a part (below Backstage's grain: a file, a prompt, a setting) | a `Component` with `spec.subcomponentOf` |
| an interface | `API`, joined with `providesApis` and `consumesApis`; its tests under `spec.morphogen.tests` |
| something the system relies on and does not own (a database, a model service) | `Resource`, joined with `dependsOn` |
| who owns or approves | `Group` or `User` |
| the role a part plays | a `Component` of `spec.type: role`, or the part's `spec.morphogen.fills` when it is an option; name the role so another part could do it ("the store's embedding model", "drivetrain") |
| an option for a role | a `Component` with `spec.lifecycle: candidate` (the catalog skill) |

Morphogen's own fields go under **one key**, `spec.morphogen`, so they never clash with fields Backstage adds.
Annotation values must be strings. Fields are described in `schemas/morphogen-spec.v1.json` (a draft).

A role is interchangeable when its interfaces are named exactly enough to check: an API and its version, a file
format, a protocol, a socket size, a skill set. An interface named loosely ("an API") makes everything look
interchangeable.

The words, for the judge:

- **Cell:** a part that can be changed and judged on its own: a module, a prompt, a config key, a
  skill, a service, a model choice. Cells nest (`in`); a cell's **scope** is it and everything
  inside it.
- **Interface:** a promise between cells, joining the cells that `provides` and `consumes` it.
  Its tests are what the promise means; an interface without tests is a hope. Mark one open to
  the world with `external: consumes` (the system offers it: an API, the whole system's behaviour)
  or `external: provides` (the system relies on it: a model API, a database it does not own).
- **What may change:** a cell's `change` lists the paths a candidate may edit and the settings it
  may set within bounds. Nothing else may change: the judge refuses a candidate that touches
  anything outside, so the bench, the scorer, the tests and the map itself are safe by default.
  `keep` holds a setting fixed inside a file `change` opens.
- **How it is judged:** `run` (the workload), `better` (the primary metric and its direction),
  `tests` (must pass), and optionally `score` (a scorer for outputs that are scored, not timed).
- **Intended against observed:** the map you write is the intent. What the running system does
  (traces, imports, calls) is the observed structure, in the same format; laying one over the
  other shows convergence, absence (intended, not there) and divergence (there, not intended).

```yaml
# catalog/classify.yaml: the part, the interface it provides, and who consumes it
apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  name: classify
  annotations:
    morphogen.dev/evidence: |
      stated | targets/classify/classify.py:L1-12 | "THRESHOLD = 50  # cut-off for a label"
spec: {type: library, lifecycle: production, owner: group:default/team, system: app, providesApis: [labels]}
---
apiVersion: backstage.io/v1alpha1
kind: API
metadata: {name: labels}
spec: {type: openapi, lifecycle: production, owner: group:default/team, definition: "see contracts/labels.md"}
```

The cell's rules go on the entity it judges, under `spec.morphogen` (the project root's
`catalog-info.yaml`, or a file a `Location` in it names):

```yaml
apiVersion: backstage.io/v1alpha1
kind: System
metadata: {name: app}
spec:
  owner: team
  morphogen:                              # once per project: its settings, and defaults every cell inherits
    sandbox: podman
    defaults: {rounds: {warmup: 0, repeats: 4, max_repeats: 8}, timeout: 60}
---
apiVersion: backstage.io/v1alpha1
kind: Component
metadata: {name: classify}
spec:
  type: library
  lifecycle: production
  owner: team
  system: app                             # a part below the grain of another is a Component with subcomponentOf
  providesApis: [labels]
  morphogen:
    dir: targets/classify                 # where its commands run (default: the root)
    change: targets/classify/classify.py#THRESHOLD in 0..100   # or a path or glob: src/**, prompts/
    run: python bench.py
    better: accuracy higher               # plain names: wall_seconds, cpu_seconds, max_rss_kb, or scored
    score: python score.py                # scores each run's output, from the base
    tests: python -m unittest -q test_classify
---
apiVersion: backstage.io/v1alpha1
kind: API
metadata: {name: labels}
spec:
  type: openapi
  morphogen:
    tests: python -m unittest -q contracts.test_labels   # run from the root
```

An entity with no `run` (and no tests) is structure, not a judged cell. An option for a role
(`spec.lifecycle: candidate`) and a role (`spec.type: role`) are never cells. Every catalog file the judge
reads (the root and each `Location` target) is a rule file: a candidate that changes one is refused, so
write the cell's rules before the operator merges the map, never in the same branch as the improvement.

Settings: `path#NAME` is a module-level constant in a Python file, `path:dotted.key` a key in YAML,
JSON or TOML; `in lo..hi` or `in [a, b]` bounds it. Optional on a cell: `same_as_base: {gen, run}`
(outputs must match the base on generated inputs), `observe: otel`, `guard: false` or `guard:
{max_regression: 0.05}` (how much the enclosing system may get worse when this cell is judged).
Held-out answers never go in the repository: the operator names them in the uncommitted
`morphogen.local.yaml` (`cells: {classify: {private: /path}}`). Data the workload reads but that
cannot be committed goes there too, as `inputs: /path` (read from `MORPHOGEN_INPUTS`).

## 2. Start with `status`, and smaller than you think

Call `status` first (or `morphogen status`). It reports the sources (the catalog,
`morphogen.local.yaml`, catalog files nothing names), each cell on the trunk and whether the judge can
judge it, cells drafted but not yet on the trunk, what is missing, and the next step. Follow the
next step; call it again after each one.

Morphogen needs cells, not a complete map. Measure first; map what earns attention.

- **Not a git repository, or no commit on `main`:** the judge reads its rules from a commit. Ask the
  operator before running `git init` or committing on their behalf.
- **A Backstage catalog already:** do not rewrite it. Add `spec.morphogen` to the one entity to improve
  (and the System's settings if the project needs any), and nothing else. A catalog file the root
  `catalog-info.yaml` does not name is not read: name it as a `Location` target.
- **No catalog:** write the entities for the parts that matter (section 1), nothing more.
- **Nothing here yet:** ask the operator what to improve and how they would know it improved.
  Draft one cell for that: `change` (as narrow as the job allows), `run`, `better` and `tests`.
  Stop there unless several parts are in play.
- **One cell exists:** add cells around it only when a change could break something outside it, or
  when the operator wants the system around it guarded (give the system a `run`).
- **A whole system:** the cells you need are the ones a change will touch, their neighbours, and
  the system that contains them (it gets a `run` so the system guard has something to measure).

Before handing over, `status` on your branch must show no problem for the cells you drafted: a
cell with a `run` and no `change`, or a primary metric the judge cannot measure, is reported there
exactly as the judge would refuse it.

## 3. Find what is there, cheapest first

Record each finding as you go: the claim, the source (file and line, URL, command and its output, or
"operator, interview"), the quoted text, and its trust (`stated` for what a document or person says, `inferred`
for what you concluded). Write it on the entity as the `morphogen.dev/evidence` annotation (one claim per line,
`trust | source | quote`) and, with Morphogen's MCP server, log it with `evidence_note`, so the map points at
evidence instead of asking to be believed. Copy a quote from the file (print the lines, do not retype them) and
quote one locator the same way each time. What a person tells you is theirs: quote the conversation as the
source and say so. What you cannot cite, leave out or ask about.

1. **Read descriptors the project already has,** Backstage's catalog first. Translate, do not copy
   wholesale:

   | Found | Becomes |
   |---|---|
   | Backstage `catalog-info.yaml`: Component, System, `subcomponentOf`, `providesApis`, `consumesApis` | do not translate: name it in `backstage:` and Morphogen reads it (cells named `component:default/x`); add only what it lacks |
   | OpenAPI, protobuf, GraphQL schemas | interfaces; the schema's examples are the first tests |
   | compose files, Kubernetes manifests, Helm values | containment; env and config keys as settings |
   | CycloneDX or package manifests | external `provides` interfaces (libraries, models, services) |
   | package layout, imports, entry points | code cells and who consumes whom |
   | prompts, skills, hooks, MCP tools, model choices | text or alternatives cells: `Component`s nested with `subcomponentOf`, below Backstage's grain |

2. **Read the code and the tests.** Existing tests are intent someone already wrote down; attach
   each to the interface it actually exercises.
3. **Run it.** Run the test suite and the workload, with a profiler or OpenTelemetry where the
   project has them. Hot spots by time, cost or errors are candidate cells; calls you see are the
   observed structure. Save an observed structure alongside, in the same entity format, if you build one.
4. **Interview the operator,** last and briefly, with what you found in hand. Ask only what the
   system cannot tell you: what must never change, which settings are theirs (owner `operator`),
   the acceptable ranges for the rest, what "better" means and what it may not cost, and any
   interface you inferred but could not confirm.

## 4. Write intent as tests

- An interface's tests say what it promises, not how today's code happens to do it. Test through
  the interface (the call, the file format, the HTTP response), with cases that would catch a
  plausible wrong implementation, including near-misses.
- A test that the current system fails is allowed: it records an absence (intent not yet built),
  and is the builder's next job. Say so in the draft.
- The tests belong to the intent. Whoever builds or optimizes the cells must not be the one who
  weakens them; the judge takes them from the base commit for this reason.
- Leave held-out answers out of the repository. If a cell's `score` needs them, the operator keeps
  them outside it and names them in the uncommitted `morphogen.local.yaml`.

## 5. Check, render, hand over

- `structure_check`: no errors (unknown parents or interfaces, cycles, gaps where something is
  consumed and nothing provides it). Warnings for untested or unused interfaces are a to-do list:
  report the intent coverage (tested interfaces out of all).
- `structure_scope(cell)` for each cell you expect to be changed: is the boundary what you meant?
- `structure_render` (Mermaid; with an observed structure, the comparison) for the operator.
- Name Morphogen's MCP tools by the server's own names (`status`, `structure_check`, ...), not by a harness prefix.
- `morphogen.local.yaml` (held-out paths, the sandbox) goes in `.gitignore`; `status` warns if it
  is committed or not ignored.
- Commit the draft on its own branch and give the operator: the rendered map, the coverage, the
  owners and ranges you chose and why, the open questions, and the evidence records behind the
  claims. It reaches main by pull request, by the operator's decision. Until then, `probe` can
  practise against it; no verdict rests on it.

## What not to do

- Do not map everything. A cell no one will change or guard is noise in every scope.
- Do not invent an ontology per project. Backstage's kinds are what the judge reads; other
  vocabularies are sources to translate from, and renders for people.
- Do not call a database or a kernel's tools: the map is files, whatever the harness.
- Do not mark a setting `agent`-owned to make later tuning easier. When unsure, `operator`.
- Do not record a guess as `stated`. Only a source states; you infer.
