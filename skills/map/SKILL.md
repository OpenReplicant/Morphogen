---
name: map
description: Map a system into Morphogen's cell format (cells, interfaces, what may change, intent as tests) so it can be measured and improved, or start a project that has no map. Use when the user asks to map, model or inventory a system, asks what a system is made of, wants to start Morphogen on a project with no morphogen.yaml, or hands over a system for a builder agent to create or change.
---

# Mapping a system for Morphogen

The map says what the system is made of and what it promises. The judge reads it from the base
commit, so a map counts only once the operator has approved it and it is on main. Your job is a
draft the operator can approve: small, checked, every claim traceable to where you found it.

## 1. What a map is

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
# morphogen.yaml, at the project root
cells:
  app: {}
  classify:
    in: app
    dir: targets/classify                 # where its commands run (default: the root)
    change: targets/classify/classify.py#THRESHOLD in 0..100   # or a path or glob: src/**, prompts/
    run: python bench.py
    better: accuracy higher               # plain names: wall_seconds, cpu_seconds, max_rss_kb, or scored
    score: python score.py                # scores each run's output, from the base
    tests: python -m unittest -q test_classify
    provides: labels
  report: {in: app, consumes: labels}
interfaces:
  labels: python -m unittest -q contracts.test_labels   # run from the root
```

Settings: `path#NAME` is a module-level constant in a Python file, `path:dotted.key` a key in YAML,
JSON or TOML; `in lo..hi` or `in [a, b]` bounds it. Optional on a cell: `same_as_base: {gen, run}`
(outputs must match the base on generated inputs), `observe: otel`, `guard: false` or `guard:
{max_regression: 0.05}` (how much the enclosing system may get worse when this cell is judged).
Held-out answers never go in the repository: the operator names them in the uncommitted
`morphogen.local.yaml` (`cells: {classify: {private: /path}}`). Data the workload reads but that
cannot be committed goes there too, as `inputs: /path` (read from `MORPHOGEN_INPUTS`).

## 2. Start with `status`, and smaller than you think

Call `status` first (or `morphogen status`). It reports the sources (`morphogen.yaml`,
`morphogen.local.yaml`, Backstage catalog files), each cell on the trunk and whether the judge can
judge it, cells drafted but not yet on the trunk, what is missing, and the next step. Follow the
next step; call it again after each one.

Morphogen needs cells, not a complete map. Measure first; map what earns attention.

- **Not a git repository, or no commit on `main`:** the judge reads its rules from a commit. Ask the
  operator before running `git init` or committing on their behalf.
- **A Backstage catalog, no `morphogen.yaml`:** do not translate the catalog. Write
  `morphogen.yaml` with `backstage: [catalog-info.yaml]` and add only what the catalog lacks, for
  the one part to improve, under its ref (`component:classify` is enough).
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

Record each finding as you go with `evidence_note`: the claim, the source (file and line, URL,
command and its output, or "operator, interview"), and its trust (`stated` for what a document
or person says, `inferred` for what you concluded). The map then points at evidence instead of
asking to be believed.

1. **Read descriptors the project already has,** Backstage's catalog first. Translate, do not copy
   wholesale:

   | Found | Becomes |
   |---|---|
   | Backstage `catalog-info.yaml`: Component, System, `subcomponentOf`, `providesApis`, `consumesApis` | do not translate: name it in `backstage:` and Morphogen reads it (cells named `component:default/x`); add only what it lacks |
   | OpenAPI, protobuf, GraphQL schemas | interfaces; the schema's examples are the first tests |
   | compose files, Kubernetes manifests, Helm values | containment; env and config keys as settings |
   | CycloneDX or package manifests | external `provides` interfaces (libraries, models, services) |
   | package layout, imports, entry points | code cells and who consumes whom |
   | prompts, skills, hooks, MCP tools, model choices | text or alternatives cells; Backstage has no grain for these |

2. **Read the code and the tests.** Existing tests are intent someone already wrote down; attach
   each to the interface it actually exercises.
3. **Run it.** Run the test suite and the workload, with a profiler or OpenTelemetry where the
   project has them. Hot spots by time, cost or errors are candidate cells; calls you see are the
   observed structure. Save an observed structure alongside, in the same format, if you build one.
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
- `morphogen.local.yaml` (held-out paths, the sandbox) goes in `.gitignore`; `status` warns if it
  is committed or not ignored.
- Commit the draft on its own branch and give the operator: the rendered map, the coverage, the
  owners and ranges you chose and why, the open questions, and the evidence records behind the
  claims. It reaches main by pull request, by the operator's decision. Until then, `probe` can
  practise against it; no verdict rests on it.

## What not to do

- Do not map everything. A cell no one will change or guard is noise in every scope.
- Do not invent an ontology per project. The format above is what the judge reads; other
  vocabularies are sources to translate from, and renders for people.
- Do not mark a setting `agent`-owned to make later tuning easier. When unsure, `operator`.
- Do not record a guess as `stated`. Only a source states; you infer.
