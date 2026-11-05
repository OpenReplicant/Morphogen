---
name: map
description: Map a system into Morphogen's structure (cells, interfaces, parameters, intent as tests) so it can be measured and improved, or start a project that has no map. Use when the user asks to map, model or inventory a system, asks what a system is made of, wants to start Morphogen on a project with no target.yaml or cells.yaml, or hands over a system for a builder agent to create or change.
---

# Mapping a system for Morphogen

The map says what the system is made of and what it promises. The judge reads it from the base
commit, so a map counts only once the operator has approved it and it is on main. Your job is a
draft the operator can approve: small, checked, every claim traceable to where you found it.

## 1. What a map is

- **Cell:** a part that can be changed and judged on its own: a module, a prompt, a config key, a
  skill, a service, a model choice. Cells nest (`parent`); a cell's **scope** is it and everything
  inside it.
- **Interface:** a promise between cells, joining the cells that `provides` and `consumes` it.
  Its `tests` are what the promise means; an interface without tests is a hope. Mark one open to
  the world with `external: consumes` (the system offers it: an API, the whole system's behaviour)
  or `external: provides` (the system relies on it: a model API, a database it does not own).
- **Parameter:** a setting in a file, with an owner. `agent` may change it within `range` or
  `choices`; `operator` and `judge` settings are never changed by a candidate.
- **Measure:** a cell's `measure` is a directory with a `target.yaml`: how the judge runs and
  scores it.
- **Intended against observed:** the map you write is the intent. What the running system does
  (traces, imports, calls) is the observed structure, in the same format; laying one over the
  other shows convergence, absence (intended, not there) and divergence (there, not intended).

```yaml
# cells.yaml (or the path in morphogen.yaml `structure`)
cells:
  app: {}
  classify:
    parent: app
    at: targets/classify/classify.py      # a path, path#symbol, path:key, or another address
    modality: code                        # text | code | numeric | workflow | alternatives | ...
    measure: targets/classify             # relative to this file's directory, else the repo root
    provides: [labels]
    parameters:
      threshold: {file: targets/classify/classify.py, name: THRESHOLD, owner: agent, range: [0, 100]}
  report: {parent: app, consumes: [labels]}
interfaces:
  labels:
    tests: ["python -m unittest -q contracts.test_labels"]   # run from this file's directory
    files: [contracts/test_labels.py, contracts/__init__.py] # belong to the intent; the judge uses the base's copies
```

A `parameter` takes exactly one of `name` (a module-level constant in a Python file) or `key` (a
dotted key in YAML, JSON or TOML). Optional on a cell: `guard: false`, or `guard:
{max_regression: 0.05}` (how much the enclosing system may get worse when this cell is judged).

## 2. Start smaller than you think

Morphogen needs cells, not a complete map. Measure first; map what earns attention.

- **Nothing here yet** (no `target.yaml`, no `cells.yaml`): ask the operator what to improve and
  how they would know it improved. Draft one `target.yaml` for that: the workload (`measure.run`),
  the harness files the judge owns, a `check`, the primary metric and its direction, and the
  parameters with owners. Stop there unless several parts are in play.
- **One target exists:** add a structure only when a change could break something outside the
  target, or when the operator wants the system around it guarded.
- **A whole system:** the cells you need are the ones a change will touch, their neighbours, and
  the system that contains them (it gets a `measure` so the system guard has something to run).

## 3. Find what is there, cheapest first

Record each finding as you go with `evidence_note`: the claim, the source (file and line, URL,
command and its output, or "operator, interview"), and its trust (`stated` for what a document
or person says, `inferred` for what you concluded). The map then points at evidence instead of
asking to be believed.

1. **Read descriptors the project already has.** Translate, do not copy wholesale:

   | Found | Becomes |
   |---|---|
   | Backstage `catalog-info.yaml`: Component, System, `subcomponentOf`, `providesApis`, `consumesApis` | cells, `parent`, `provides`, `consumes` |
   | OpenAPI, protobuf, GraphQL schemas | interfaces; the schema's examples are the first tests |
   | compose files, Kubernetes manifests, Helm values | containment; env and config keys as parameters |
   | CycloneDX or package manifests | external `provides` interfaces (libraries, models, services) |
   | package layout, imports, entry points | code cells and who consumes whom |
   | prompts, skills, hooks, MCP tools, model choices | text or alternatives cells; Backstage has no grain for these |

2. **Read the code and the tests.** Existing tests are intent someone already wrote down; attach
   each to the interface it actually exercises.
3. **Run it.** Run the test suite and the workload, with a profiler or OpenTelemetry where the
   project has them. Hot spots by time, cost or errors are candidate cells; calls you see are the
   observed structure. Save an observed `cells.yaml` alongside if you build one.
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
- Leave held-out answers out of the repository. If a measure needs them, the operator keeps them
  outside it (`measure.score.private`).

## 5. Check, render, hand over

- `structure_check`: no errors (unknown parents or interfaces, cycles, gaps where something is
  consumed and nothing provides it). Warnings for untested or unused interfaces are a to-do list:
  report the intent coverage (tested interfaces out of all).
- `structure_scope(cell)` for each cell you expect to be changed: is the boundary what you meant?
- `structure_render` (Mermaid; with an observed structure, the comparison) for the operator.
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
