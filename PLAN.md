# Plan: Morphogen small, with everything above it plugged in

Morphogen keeps the part nothing else provides: a judge the improver cannot edit, the "still
works" gate, the system guard and the evidence log. Everything else is a source it reads or a slot
it fills:

```
business:  ArchiMate (intended)            OCEL event logs, process mining (observed)
software:  Backstage catalog-info.yaml     traces, OpenTelemetry
cells:     Morphogen cells                 the judge's measurements
            ^ reads whichever are present; adds only the cell grain and what the judge needs
optimizers (grid, Optuna, GEPA, a model quorum): a space, an evaluator they do not hold, one verdict
```

Each phase is one pull request. A phase that changes the judge starts with its cheats in the red
team, and ends with the whole suite passing locally and in Podman.

## The cell format

Core fields, plus optional ones and one interfaces map:

```yaml
cells:
  classify:
    in: app                                # a cell, or a Backstage ref (component:default/labeller)
    change: classify.py#THRESHOLD in 0..100   # what may change; nothing else may
    run: python bench.py                   # the workload, from the base
    better: accuracy higher                # the primary metric and its direction
    tests: python -m unittest -q test_classify   # must pass; refuses, never trades against score
    score: python score.py                 # optional: scores the output, from the base
    observe: otel                          # optional: metrics collected outside the run
interfaces:
  labels: python -m unittest -q contracts.test_labels   # or {tests: [...], external: consumes}
```

- **Default deny:** a candidate may change only what some cell's `change` names; everything else
  comes from the base. This replaces `harness`, interface `files`, the special case for the
  structure file, and the check for files that shadow standard modules.
- **`change` forms:** a path or glob (a code or text cell; GEPA's artifact), `path#NAME in lo..hi`
  or `in [a, b]` (a Python constant), `path:dotted.key in ...` (YAML, JSON, TOML). Settings with a
  range or choices are the agent's; a setting named without one is fixed.
- **Tests are one kind:** commands. `same_as_base: {gen, run}` is the generated-inputs test,
  replacing `equivalence`; a cell's `tests` replace `check`.
- **`better`** has a long form for the few cells that need it:
  `{accuracy: {higher: true, min: 0.02}, wall_seconds: {lower: true, max_regression: 0.5}}`.
- **Defaults stay out of the file:** rounds, aggregation, gain kind, `interface: direct`,
  timeout. `guard` stays optional on a cell.
- **Local, not committed:** held-out answer paths (`private`, `search`), budget overrides and the
  sandbox, in an uncommitted `morphogen.local.yaml`.

## Phases

### 0. Land what is on the branch; write "What Morphogen is"
- Pull request for the cell gate by path, the base-tests fix and the map skill (on the branch).
- A one-page "What Morphogen is" at the top of BRIEF.md: the core, the cell format, the layers
  above, the optimizer contract, and what belongs to the family (mapper, builder, domain modules,
  the knowledge base). The rest of the brief stays as rationale. README's opening follows it.

**Done when** both are on main.

### 1. The loader and default deny (done on the branch, 2026-11-05)
- Red team first, against today's judge and then the new one:
  - edit a file outside `change`;
  - add a new file outside it (`conftest.py`, `sitecustomize.py`, a module shadowing a
    standard one);
  - a symlink inside `change` that points outside it;
  - `..` in a path to escape;
  - widen `change` in the candidate's own copy of the file (the base's copy must win);
  - change a setting beyond its range.
- `documents.py` compiles the cell format into the judge's existing internal form, so
  `judge.py` changes little: default deny replaces `_forbidden` and the harness overlay.
- The old format (`target.yaml` plus `cells.yaml`) compiles through the same loader, so nothing
  breaks while things move. `morphogen migrate` writes the new format from the old.
- A/A check after (the statistics do not change, but their inputs come through a new loader).

**Done when** both formats judge the fixtures identically, and every cheat, old and new, fails.

### 2. Move everything onto it
- Test fixtures and the fixture projects (`fixture_scored`, `fixture_system`, `fixture_agent`):
  new format; the red team runs against the new format only.
- `demos/entity-resolution`: its draft `cells.yaml` in the new format, its F1 moved into a
  scorer from the base, contract tests for its untested interfaces.
- `demos/cognitive-model`: convert the rebuild 6 map (`rebuild-6-map/lists`) to cells with a
  script; keep the old lists as the record.
- `demos/catalog`: its brief in the new terms.
- The `morphogen` and `map` skills, MCP tool descriptions, CLI help, the web UI, README and
  CLAUDE.md.
- Then remove the old format from the loader, or keep it read-only (decision below).

**Done when** no file in the repository uses `harness`, `check`, `equivalence` or `target.yaml`,
except the migration test.

### 3. Sources above: Backstage, level 1
- Read `catalog-info.yaml` directly, with no Backstage running:

  | Backstage | Becomes |
  |---|---|
  | `Component`, `System`, `Domain` | cells |
  | `subcomponentOf`, `system`, `domain` | `in` |
  | `API` (with its `definition`) | an interface |
  | `providesApis`, `consumesApis` | provides, consumes |
  | `Resource` via `dependsOn` | an `external: provides` interface |

- `in: component:default/x` refs from the cell file.
- A coarse cell as annotations on an entity: `morphogen.dev/change`, `/run`, `/better`, `/tests`.
- `structure check` reports which source each cell and interface came from, and conflicts between
  sources.
- Test with Backstage's example entities (check their licence first).

**Done when** the entity-resolution demo can be described half in `catalog-info.yaml`, half in the
cell file, and judges the same as before.

### 4. The optimizer contract, and GEPA
- Name the contract in `optimize.py`: `space` (from `change`: numbers, choices, text),
  `evaluate(candidate) -> score, diagnostics` (a probe; the diagnostics are failing tests and the
  scorer's per-case misses), and one `judge` of the best.
- Text cells in the space: a file's whole content as the candidate.
- GEPA adapter as an optional extra (check licence and pin). Its proposer needs a model: run it
  through `claude -p` on the operator's subscription if GEPA accepts a custom model callable;
  check this first.
- Escaping local optima in the same pass: random restarts, simulated annealing, a stagnation
  signal for the selector.

**Done when** GEPA improves a text cell in a fixture through `tune`, and the judge passes it.

### 5. A fresh start
- `status` (CLI and MCP): which sources exist, which cells are on the base, what is missing, and
  the next step.
- The `map` skill writes the new format, and reads `catalog-info.yaml` first.
- The plugin at 0.8.0; README's install section.

**Done when** an empty repository gets from `status` to a judged first cell by following the
skill.

### 6. First real runs
- Entity resolution: one optimizer on `matcher` and one on `blocking`, with held-out F1 (the demo's
  own "done when").
- The mapper as a target: the map skill tuned by GEPA against gold maps of three or four small
  systems held outside the repository.
- An agent target measured by the `otel` observer.

## Later, in the family (not in this plan)
- ArchiMate exchange files and OCEL 2.0 event logs as sources (business processes as cells,
  judged by replay with `trust: simulated`; PM4Py is AGPL, so an external tool, not a dependency).
- Backstage levels 2 and 3: the catalog REST API, and a plugin publishing verdicts as Tech Insights
  facts plus a template that adds a cell.
- The online stage: canary after apply; learner cells judged by replay.
- The UI/UX quorum as a scorer demo.
- Re-judging past verdicts when the judge gains a rule (as anti-doping retests stored samples): the
  evidence log holds each verdict's commits, so a new red-team rule can flag earlier passes that
  only passed through the hole it closes.
- Domain modules around a shared knowledge base, joined by the resolver.

## Decisions (operator, 2026-11-05)
1. **One file:** the cell format and project settings live in `morphogen.yaml` at the root;
   held-out paths, budget overrides and the sandbox in an uncommitted `morphogen.local.yaml`.
2. **The old format** (`target.yaml` plus `cells.yaml`) is removed after phase 2.
3. **The field is `change`.**
4. **Phase 3 (Backstage) before phase 4 (GEPA).**
