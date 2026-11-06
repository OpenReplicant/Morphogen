# Morphogen

**A judge for self-improving systems.** Point any optimizer or coding agent at part of a system (a
prompt, a setting, a function, a skill, a service) and Morphogen decides whether the change is
really better: by rules taken from the last approved version, with measurements taken outside the
code, on cases the optimizer never saw, without breaking a neighbour or making the whole system
worse. Every verdict goes into a log that cannot be quietly edited.

Morphogen does not propose changes. Optimizers do that, and they plug into it. Tools that describe
a system, such as Backstage, sit above it. [BRIEF.md](BRIEF.md) is the design (its first section is
the one-page version) and [PLAN.md](PLAN.md) the way there; this file is the case for Morphogen and
how to use what is built.

## Why a judge, on top of optimizers

**An optimizer is only as honest as its evaluator.** It maximises whatever score it is given. Give a
strong optimizer, or a capable coding agent, a weak evaluator, and the stronger it is, the faster it
finds the gaps:

- **It edits the test**, or the benchmark, or the scorer, so the score rises and nothing improves.
- **It reads the answers.** Held-out cases in the repository are just files.
- **It wins locally and loses globally**, shifting work onto code only the system runs.
- **It keeps a lucky run.** Noise looks like progress when nobody checks it statistically.

This is Goodhart's law at machine speed. The Darwin Gödel Machine reported an agent scoring
perfectly by removing the signal its checker read; every item above is a test in this repository.

**So the judge is the scarce part.** Optimizers are abundant and getting better fast: Optuna, GEPA,
OpenEvolve, coding agents, quorums of models. A judge that holds its rules fixed, measures from
outside, keeps answers out of reach, protects neighbours and the whole, and remembers every cheat
it has seen is rare. Morphogen is that judge, plus the map of what may change.

**That is why optimizers plug in rather than compete.** Every optimizer gets the same contract:

- **a space**, from what the cell may change (numbers and choices for Optuna, text for GEPA, code
  for an agent);
- **an evaluator it does not hold**, the probe, which also returns diagnostics (failing tests,
  per-case misses) for optimizers that learn from them;
- **one verdict**, on its best candidate, from the judge.

Morphogen's claim is not "better changes than GEPA". It is that GEPA's changes, or anyone's, can be
trusted enough to merge.

**Why build systems with it, rather than let coding agents run.** Each change that reaches main has
passed a judge it could not influence, so improvements accumulate instead of quietly eroding what
was there. The agent is free to try anything inside what its cell may change; it cannot redefine
success.

### The judge evolves, between searches

Within a search the judge is frozen: its rules come from the base commit, so the optimizer cannot
co-adapt with it, as a GAN's generator does with its discriminator. Between searches it gets
stronger, through a ratchet with a person in it:

1. Someone finds or imagines a way to cheat.
2. It goes into the red team as a test, and must pass the current judge, which proves the hole.
3. The judge is fixed; the cheat now fails.
4. The fix reaches main by a reviewed pull request, since the judge used next is whatever main holds.
5. Every earlier cheat must keep failing.

No judge is ungameable. What Morphogen contributes is a judge that cannot be optimised against
while it judges, and that only gets stricter, never quietly weaker.

### Beyond software

The pattern is older than software, wherever people optimise against a measure:

- **Clinical trials** freeze the judge before the data (preregistration) and blind the measurement.
- **Exams** hold the questions out.
- **Audits** separate who reports from who checks.
- **Anti-doping** is the closest match: new tests are added as new cheats are found, and stored
  samples are retested years later under the new tests.

Morphogen applies that discipline to systems that change themselves. The open question is the same
everywhere: how hard the judge is to game. A planned addition borrows anti-doping's best idea:
re-judging past verdicts when the judge gains a rule, to flag passes that only passed through the
hole it closes.

## The cell format

One `morphogen.yaml` at the project's root:

```yaml
cells:
  app: {}
  classify:
    in: app                                   # the cell this one belongs to
    dir: classify                             # where its commands run (default: the root)
    change: classify/classify.py#THRESHOLD in 0..100   # what may change; nothing else may
    run: python bench.py                      # the workload
    better: accuracy higher                   # the primary metric and its direction
    score: python score.py                    # scores each run's output, from the base
    tests: python -m unittest -q test_classify   # must pass; a failure refuses
    provides: labels
  report: {in: app, consumes: labels}
interfaces:
  labels: python -m unittest -q contracts.test_labels   # run from the root
```

- **Default deny.** A candidate may change only what the judged cell's scope names in `change`.
  Anything else changed, the project file, the bench, the scorer and every test included, refuses
  the candidate before anything runs. Candidates may not add symbolic links.
- **`change`**: a path or glob (`src/**`, `prompts/`), or a setting: `path#NAME` (a Python constant)
  or `path:dotted.key` (YAML, JSON, TOML), bounded with `in lo..hi` or `in [a, b]`. A setting entry
  lets only that setting change in its file. `keep: path#NAME` holds a setting fixed inside a file
  `change` opens.
- **`better`**: `metric higher|lower`, comma-separated for constraints after the primary, or the long
  form `{accuracy: {higher: true, min: 0.05, gain: absolute, aggregate: mean}}`. Plain names are the
  judge's (`wall_seconds`, `cpu_seconds`, `max_rss_kb`), else from `observe`, else from `score`.
- **Optional:** `observe` (`otel`, or a command collected outside), `same_as_base: {gen, run, cases}`
  (outputs must match the base on freshly generated inputs), `rounds`, `timeout`, `guard`,
  `simulates`, `requires`, `description`.
- **Held-out answers** never go in the repository. The operator names them in an uncommitted
  `morphogen.local.yaml`: `cells: {classify: {private: /outside/the/repo, search: /another}}`.
  Verdicts score against `private`; probes, and so every optimizer, against `search`. Data the
  workload reads but that cannot be committed (a licence, its size) is named the same way as
  `inputs`: every run reads it from `MORPHOGEN_INPUTS`, a container mounts it read-only, and the
  judge refuses a verdict if it changed during the runs. It must lie outside the repository and
  away from the answers. The local file may also set `sandbox` and `budget`.

Name a cell to judge as `cell:classify`, `classify`, or its `dir`. A project with nothing yet starts
with one cell; the `map` skill drafts it with you.

### Backstage above it

A project that already keeps Backstage's `catalog-info.yaml` files need not restate its structure.
`backstage: catalog-info.yaml` (or a list) in `morphogen.yaml` reads them directly, with no
Backstage server, following `Location` targets inside the project:

| Backstage | Becomes |
|---|---|
| `Component`, `System`, `Domain` | a cell, named by its ref: `component:default/classify` |
| `subcomponentOf`, `system`, `domain`, `subdomainOf` | `in` |
| `API` | an interface, named by its ref; its tests from the annotation `morphogen.dev/tests` |
| `providesApis`, `consumesApis` | `provides`, `consumes` |
| `dependsOn` | consumes it: provided by that cell, or external (a `Resource`) |
| annotations `morphogen.dev/change`, `keep`, `run`, `better`, `tests`, `score`, `dir`, `observe` | the cell's fields (one entry per line for lists) |

`morphogen.yaml` then adds what the catalog does not hold, under the same names (`component:classify`
is enough), and may add cells below Backstage's grain with `in: component:classify`. Where the two
disagree on a field, the structure has an error and the judge refuses it; `structure check` reports
where each cell and interface came from. The catalog files are the judge's, like `morphogen.yaml`:
a candidate that changes one is refused, whatever `change` says. `demos/entity-resolution` is
described this way.

## In Claude Code

```
/plugin marketplace add OpenReplicant/Morphogen
/plugin install morphogen@morphogen
```

Install it from GitHub, not from a local clone: a clone added as a marketplace runs the plugin from
the clone itself, so the judge would be the candidate you are changing. To move to a newer version,
`/plugin marketplace update morphogen`, then `/plugin update morphogen@morphogen`, and restart
Claude Code. The plugin brings the MCP server, the `morphogen` skill (improve a cell honestly), the
`map` skill (draft the cells), and the `worker` and `reviewer` agents. It needs
[uv](https://docs.astral.sh/uv/) on the path.

**Starting fresh.** In a git repository, ask Claude to start Morphogen here. The map skill calls
`status`, which says where the project stands and the next step: no commit yet, no map, a map
drafted but not on `main`, a cell the judge cannot judge yet (and why), a cell to measure, a cell
to improve. It reads a Backstage `catalog-info.yaml` if there is one. The first map is one cell,
the part you want improved, with what may change, how to run it, what "better" means and the tests
it must keep passing; it reaches `main` by your pull request, and only then does a verdict rest on
it.

## From the command line

```
uv sync
uv run morphogen status                         # where the project stands; the next step
uv run morphogen structure check morphogen.yaml
uv run morphogen measure cell:classify
uv run morphogen judge cell:classify my-branch
uv run morphogen tune cell:classify              # the selector chooses optimizers
uv run morphogen optimizers                      # the catalog
uv run morphogen evidence --verify
uv run morphogen ui                              # http://127.0.0.1:8765/
```

Python 3.11 or later and [uv](https://docs.astral.sh/uv/); pydantic, PyYAML and the MCP SDK (all
MIT, pinned in `uv.lock`); Optuna 5.0.0 and GEPA 0.1.4 (both MIT) as optional extras
(`uv sync --extra optuna --extra gepa`).

### Optimizers and text cells

`tune` hands every optimizer the same three things: a **space** (each bounded setting, as a number
or a choice, and each whole file a cell's `change` names by path, as text), an **evaluate** it does
not hold (a probe, whose diagnostics are failing tests, wrong cases and metrics), and **one verdict**
on its best. Each optimizer sees only the kinds it takes: the numeric ones settings, GEPA text. A
proposal outside the space, out of bounds, or not text for a text cell is refused before anything is
written.

```
uv run morphogen tune cell:reply --optimizer gepa --trials 8
```

GEPA reflects on each probe's diagnostics with a model, by default `claude -p --model sonnet` on
your own Claude subscription (no API key), run with no tools and no MCP servers in an empty
directory, so it can only answer. The cell's `description` is its objective.

## What is built

| Part | Module | Does |
|---|---|---|
| Cell format | `project.py`, `backstage.py` | parses `morphogen.yaml` and any Backstage catalog files it names; compiles them to a structure and, per cell, the spec the judge runs; default deny |
| Structure | `structure.py`, `render.py` | cells in a containment tree, interfaces as hyperedges with their tests; checks, scopes, computed boundaries, intent coverage, intended against observed, a Mermaid diagram |
| Judge | `judge.py`, `runner.py` | scores a candidate commit against a base by the base's rules; `probe` gives practice feedback; `measure` records a baseline |
| Evidence | `evidence.py` | an append-only, hash-chained log of measured and stated claims, in git's own directory |
| Observers | `observers.py` | `command` (a command after each run) and `otel` (an OpenTelemetry receiver in the judge that adds up each run's telemetry, such as Claude Code's cost, tokens and tool results) |
| Optimizers | `optimize.py` | a catalog behind one contract: grid, random, hill-climb (with `restarts`) and simulated annealing (`anneal`), built in; Optuna and GEPA adapters (optional extras); and the `selector`, whose bandit policy (primed by earlier verdicts, with a stagnation signal) chooses which proposes next. A model-based policy is planned; packages add more through the `morphogen.optimizers` entry point. `tune` checks, writes and probes each proposal and judges the best |
| Interfaces | `cli.py`, `mcp_server.py`, `ui.py` | the command line, an MCP server with 11 tools, and a local read-only web UI |
| Plugin | `.claude-plugin/`, `skills/`, `agents/` | the Claude Code plugin around the MCP server |

### The system guard

Improving one part can make the whole worse: a cell can win on its own benchmark by shifting work
onto code only the system runs. So when a cell is judged, its topmost ancestor with a `run` (the
system) is measured too, base against candidate, in paired rounds, with every metric a constraint:
the system's primary metric may regress at most 5% (`guard: {max_regression: 0.1}` on the cell to
change it, `guard: false` to turn it off). The verdict records the comparison under `system`.

### Optimizing agents

An agent is a system like any other: its harness (Claude Code, its settings, skills, prompts, hooks,
MCP servers, subagents) becomes cells, measured on a fixed task set. Claude Code reports its own
usage over OpenTelemetry, so cost, tokens and failed tools are observed outside the candidate:

```yaml
cells:
  agent:
    change: [agent/skills/**, "agent/settings.json:model in [sonnet, opus]"]
    run: python run_tasks.py
    observe:
      type: otel
      collected: outside
      metrics:
        cost_usd: {metric: claude_code.cost.usage}
        tool_failures: {event: claude_code.tool_result, where: {success: "false"}, count: true}
    better: {cost_usd: {lower: true, min: 0.10}}
    score: python score_tasks.py              # task success, on held-out tasks
```

Until a model gateway exists, agent cells run with `sandbox: none` (the model needs the network, and
an `otel` observer is refused in a container), and an agent's learned state is not yet reset
between trials (#45).

## What the judge guarantees

- **The rules are the base's.** `morphogen.yaml` and everything a cell's `change` does not name come
  from the base commit; a candidate that changes any of it is refused before anything runs.
- **Measurement is outside the code.** Time and memory are measured by a wrapper process; inputs
  come from a fresh seed every round; each timed run must print what the base prints (unless the
  output is scored, or `same_output: false`). Numbers the workload prints are kept as `reported.*`
  and never decide a verdict.
- **Answers are out of reach.** The base's scorer runs in its own process; only it is told where
  the held-out answers are (`MORPHOGEN_PRIVATE`); probes score against `search` instead; a
  candidate whose files name the private directory is refused. Inputs kept outside the repository
  are read-only to every run, and their digest is in every verdict.
- **Settings stay in bounds.** A setting moved outside its range or choices, a kept setting
  changed, or a setting made unreadable refuses the candidate. Every verdict records each
  setting's base and candidate values.
- **Luck is not progress.** Paired rounds in alternating order; the median (or mean) paired gain
  must clear the bar, and a sign test must reject luck at p ≤ 0.01. Identical code passed 0 of 12
  times (A/A, 2026-11-05).
- **Neighbours and the whole are protected.** The tests of every interface the cell's scope
  touches must pass, and the system guard must hold.
- **The runner says what it guarantees.** Podman by default: no network, read-only tree, only the
  candidate's tree visible, nothing kept between runs, resource limits. A cell can require them.
- **Everything is evidence:** every verdict and probe is logged as `trust: measured, by: judge`.

The red team holds the known ways to cheat: 53 of them (`tests/test_redteam.py` and the default-deny
cheats in `tests/test_cells.py`), from patching the timer to reading the held-out answers, rigging
the bench, widening `change` in the candidate's own `morphogen.yaml`, breaking a neighbour's
contract, winning locally while the system gets slower, or switching telemetry off to look free.
Every one must fail; a new one goes there first. The whole suite also runs with every trial in
Podman (`MORPHOGEN_TEST_SANDBOX=podman`), where the container-only cheats run too.

## How Morphogen compares

Details are from each project's own docs or source, read on 2026-11-04 and 2026-11-05.

| System | What it does | Relation to Morphogen | What Morphogen adds around it |
|---|---|---|---|
| **Optuna** (MIT) | samples parameter values (TPE and others), ask/tell | fills the optimizer slot (built) | which settings may change and within what bounds; probes as its objective; a verdict on held-out cases |
| **GEPA** (MIT) | evolves text with model reflection and a Pareto front; you supply the evaluator | fills the optimizer slot for text cells (built) | an evaluator out of the candidate's reach (GEPA leaves isolation to you); held-out answers; neighbours' contracts and the system guard |
| **OpenEvolve / AlphaEvolve** (Apache-2.0) | evolves marked code blocks against an evaluator | could fill the optimizer slot for code cells | OpenEvolve imports your evaluator into its own process with no sandbox; Morphogen scores outside the candidate, in a container |
| **AFlow, ADAS, Darwin Gödel Machine** | search over agent workflows, or rewrite whole agents, against benchmarks | research systems with the same aim at the whole-agent scope | the Darwin Gödel Machine reports objective hacking; Morphogen's red team and outside measurement exist for exactly that |
| **Kayenta, Argo Rollouts** | judge a canary against a baseline on metrics collected outside the code, after deploy | precedents for the judge, one stage later | judging before merge, on candidates from an agent that may cheat, with held-out cases and bounded settings |
| **Kubernetes Horizontal Pod Autoscaler** | changes one setting within operator-owned bounds from live metrics | the precedent for a local drive with owned bounds | any cell and modality, structural change, and a judge instead of a fixed rule |
| **Backstage, ArchiMate** | describe software (Backstage's catalog) or the business above it (ArchiMate) | the layers above: Morphogen reads `catalog-info.yaml` directly (built); ArchiMate is planned | the cell grain below them: what may change, how it is judged |
| **Claude Code, or any coding agent** | builds and changes code | the builder, and the agent that drives Morphogen through its MCP tools | a referee it cannot edit, so its changes are accepted on evidence, not on its own say-so |

## Limits

- **Without a container, code runs as you.** It can read any file you can: naming the private
  directory is refused, but an obfuscated path gets through. In Podman it fails, since only the
  candidate's tree is mounted. `sandbox: auto` picks Podman, then Docker, then none; a cell can
  insist with `requires: [network_isolated, private_paths_hidden, ...]`. Containers use
  `sandbox_image` (default `python:3.12-slim`), so a cell's dependencies must be in that image.
- **The scorer runs without a container**: it is the judge's code from the base commit.
- **Settings are read statically.** Code that changes a setting at run time is the reviewer's to
  catch. TOML keys can be read but not yet written by `tune`.
- **Default deny is as narrow as `change`.** `change: "**"` would open everything but the project
  file; keep each cell's `change` to what it should touch.
- **The web UI** binds to localhost, has no authentication and only reads. It loads Alpine.js 3.17.5
  and Mermaid 12.2.0 (both MIT) from cdn.jsdelivr.net, so the diagram needs network access.
- **The evidence log** refuses edits through SQLite triggers; whoever can write the file can drop
  them, and the hash chain then shows the edit.
- **Backstage is read from files only:** `$text`, `$json` and `$yaml` substitutions, URL targets and
  the catalog's REST API are not read; relations Morphogen has no use for (owners, lifecycles) are
  ignored.
- **GEPA's model calls are not sandboxed by the judge:** they run as you, through the Claude CLI,
  with tools switched off. What the model proposes can only be written into the cell's own files.
- **Not built yet:** a `status` command for fresh starts, the observed structure from traces, and
  the online stage ([PLAN.md](PLAN.md)).

## Layout

    morphogen/       the core, its CLI, MCP server and web UI
    tests/           its tests and red team; fixture projects in tests/fixture*.py
    .claude-plugin/  the plugin and marketplace manifests
    skills/, agents/ the Claude Code skills and agents
    demos/           projects Morphogen can build and drive (the core never imports from them)
    BRIEF.md         the design;  PLAN.md  the way there
