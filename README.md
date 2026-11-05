# Morphogen

The local morphological drive: improve a system at any scope, from one cell to the whole, behind
a judge the improver cannot edit. Morphogen does little on its own. It connects a system's
structure, optimizers and measurements, and keeps the improver honest. [BRIEF.md](BRIEF.md) is
the design; this file is how to use what is built.

## What is built

| Part | Module | Does |
|---|---|---|
| Structure | `structure.py`, `render.py` | `cells.yaml`: cells in a containment tree, interfaces as hyperedges with their tests, parameters with owners. Checks, scopes, computed boundaries, the tests a change in a scope must pass, intent coverage, intended against observed, a Mermaid diagram |
| Judge | `judge.py`, `runner.py` | scores a candidate commit against a base by the base's rules (see below) |
| Evidence | `evidence.py` | an append-only, hash-chained log of measured and stated claims, in git's own directory |
| Observers | `observers.py` | the observer slot: `command` (a command after each run) and `otel` (an OpenTelemetry receiver in the judge that adds up each run's telemetry, such as Claude Code's cost, tokens and tool results) |
| Optimizers | `optimize.py` | the optimizer slot: a catalog (`morphogen optimizers`) of built-in grid, random and hill-climb search, an Optuna adapter (`uv sync --extra optuna`), and the `selector`, an optimizer whose policy (a bandit on probe gains, primed by earlier verdicts) chooses which one proposes next; GEPA and a model-based selector policy are listed as planned; other packages add optimizers through the `morphogen.optimizers` entry point. `tune` probes each proposal and judges the best |
| CLI | `cli.py` | `morphogen structure`, `measure`, `judge`, `tune`, `evidence` |
| MCP server | `mcp_server.py` | the same as ten tools for an agent: `structure_check`, `structure_scope`, `structure_render`, `measure`, `probe`, `judge`, `tune`, `evidence_query`, `evidence_note` (stated or inferred only), `evidence_verify` |
| Web UI | `ui.py`, `ui.html` | `morphogen ui`: a local, read-only page (Alpine.js and Mermaid) with the structure diagram (click a cell for its scope, boundary, tests and parameters), findings and intent coverage; the evidence log with filters, verdict metrics, reasons and parameter values; and each target's primary metric, parameters and latest results |
| Claude Code plugin | `.claude-plugin/`, `skills/`, `agents/` | the MCP server, the `morphogen` skill (how to improve a target honestly), and the `worker` and `reviewer` agents |

Python 3.11 or later and [uv](https://docs.astral.sh/uv/); pydantic, PyYAML and the MCP SDK (all
MIT, pinned in `uv.lock` at the versions rebuild 6 tested).

## In Claude Code

```
/plugin install morphogen --marketplace OpenReplicant/Morphogen
```

Install it from GitHub, not from a local clone: a clone added as a marketplace runs the plugin
from the clone itself, so the judge would be the candidate you are changing.

## From the command line

```
uv sync
uv run morphogen structure check cells.yaml
uv run morphogen measure targets/my-target
uv run morphogen judge targets/my-target my-branch
uv run morphogen tune targets/my-target              # the selector chooses optimizers
uv run morphogen optimizers                          # the catalog
uv run morphogen evidence --verify
uv run morphogen ui              # http://127.0.0.1:8765/
```

A target can also be named as `cell:NAME`, for the `measure` of a cell in the project's
structure (`morphogen.yaml` key `structure`, default `cells.yaml`). Judged that way, the candidate
must also pass the tests of every interface the cell's scope touches. Those tests, the files they
list (`interfaces.<name>.files`) and `cells.yaml` itself come from the base commit, and run from
the structure file's directory; each verdict records which ran.

**The system guard.** Improving one part can make the whole worse: a cell can win on its own
benchmark by shifting work onto code only the system runs, or onto a shared resource (the Theory
of Constraints' local optimum). So when a cell is judged, its topmost ancestor cell with a
`measure` (the system) is measured too, base against candidate, in paired rounds, with every
metric a constraint: the system's primary metric may regress at most 5% (`guard: {max_regression:
0.1}` on the cell to change it, `guard: false` to turn it off), and its other metrics keep their
own limits. The verdict records the system's comparison under `system`.

## A target

A directory with a `target.yaml`. The judge reads it, and the harness files it lists, from the
base commit, so a candidate cannot change how it is scored.

```yaml
name: classify
harness: [bench.py, score.py, test_classify.py, inputs.json]   # belong to the judge
check: python -m unittest -q test_classify                       # must pass on the candidate
measure:
  run: python bench.py                     # the workload; timed from outside the process
  repeats: 4
  same_output: false                       # outputs may differ: they are scored instead
  score:                                   # scored outside the candidate
    run: python score.py                   # reads each run's output on stdin, prints {"accuracy": ...}
    private: ~/.morphogen/classify/holdout # held-out answers, outside the repository
    search: ~/.morphogen/classify/search   # what probes (the optimizer's search) score against
  metrics:
    scored.accuracy: {direction: higher, primary: true, min_improvement: 0.05, gain: absolute, aggregate: mean}
parameters:
  threshold: {file: classify.py, name: THRESHOLD, owner: agent, range: [0, 100]}
```

### Observers

An observer measures each timed run from outside the code under test; its metrics become
`observed.*`, and may decide a verdict when the target says the data is `collected: outside`.

- `command`: a command from the base commit, run after each run, printing one JSON object of
  numbers (a Prometheus query, a proxy's log, a bill).
- `otel`: an OpenTelemetry receiver inside the judge (OTLP/HTTP JSON, standard library only).
  Before each run the judge points the run's telemetry at it and tags the run with its id; after
  the run it adds up what arrived for that id. A run that sends nothing, or a negative value in a
  sum, refuses the candidate. It keeps only each run's totals: no traces, no dashboards.

```yaml
measure:
  run: python run_tasks.py                  # e.g. Claude Code on a fixed task set
  same_output: false
  observer:
    type: otel
    collected: outside                      # Claude Code itself reports, not the candidate's code
    metrics:
      cost_usd:      {metric: claude_code.cost.usage}
      output_tokens: {metric: claude_code.token.usage, where: {type: output}}
      tool_failures: {event: claude_code.tool_result, where: {success: "false"}, count: true}
  metrics:
    observed.cost_usd: {direction: lower, primary: true, min_improvement: 0.10}
```

### Optimizing agents

An agent is a system like any other: put the harness (Claude Code, its settings, skills, prompts,
hooks, MCP servers, subagents) in the structure as cells, with interfaces between them, and
measure it on a fixed task set. Claude Code reports its own usage over OpenTelemetry
(`CLAUDE_CODE_ENABLE_TELEMETRY=1`, which the `otel` observer sets with the other exporter
variables), so cost, tokens and failed tools are observed outside the candidate; task success is
scored outside it by a scorer on held-out tasks. A skill can then be tuned or rewritten under the
same judge, its neighbours' contracts and the system guard. Until a model gateway exists, agent
targets run with `sandbox: none` (the model needs the network; an `otel` observer is refused in a
container), and an agent's learned state is not yet reset between trials (#45).

The primary metric must be one the judge measures (`wall_seconds`, `cpu_seconds`, `max_rss_kb`),
one an observer collects outside the code under test (`observed.*` with `collected: outside`), or
one a scorer computes outside the candidate (`scored.*`). Numbers the workload prints are kept as
`reported.*` and never decide a verdict.

## What the judge guarantees

- The spec and harness come from the base commit and are laid over the candidate.
- Time and memory are measured by a wrapper process; inputs come from a fresh seed every round;
  each timed run must print what the base prints (unless `same_output: false`).
- Quality is scored by the base's scorer in its own process. Held-out answers live outside the
  repository; only the scorer is told where (`MORPHOGEN_PRIVATE`); probes score against `search`
  instead, so the search never sees them; a candidate whose files name the private directory is
  refused.
- Parameters: a candidate that changes one owned by the operator or the judge, sets an
  agent-owned one outside its range or choices, or makes one unreadable is refused before anything
  runs. Every verdict records each parameter's base and candidate values.
- Paired rounds in alternating order; the median (or mean) paired gain must clear the bar and a
  sign test must reject luck at p ≤ 0.01. Identical code passed 0 of 12 times (A/A, 2026-11-05).
- Files that shadow standard or harness modules, or customise the interpreter, are refused.
- Judging a cell: the tests of every interface it touches, from the base's structure, must pass,
  and the system around it must not get worse (the system guard).
- Runners declare their guarantees (Podman by default: no network, read-only tree, only the
  candidate's tree visible, nothing kept between runs, resource limits); a target can require them.
- Every verdict and probe is evidence: `trust: measured, by: judge`.

`tests/test_redteam.py` holds the known ways to cheat: 33 of them, from patching the timer to
reading the held-out answers, breaking a neighbour's contract, or winning locally while the system
gets slower, or switching telemetry off to look free. Every one must fail; a new one that passes
goes there first. The whole suite also runs with every trial in Podman
(`MORPHOGEN_TEST_SANDBOX=podman`), where the container-only cheats run too.

## How Morphogen compares

Morphogen is not another optimizer, evaluator or catalog. It is the workspace around them: it
says what may change (the structure, owners and bounds), runs a search with whichever optimizer
fits, and only accepts what a judge the improver cannot edit measures as better, for the cell and
for the system around it. Most of the tools below fit one of its slots; what Morphogen adds is the
wrapping. Details are from each project's own docs or source, read on 2026-11-04 and 2026-11-05.

| System | What it does | Relation to Morphogen | What Morphogen adds around it |
|---|---|---|---|
| **Optuna** (MIT) | samples parameter values (TPE and others), ask/tell interface | fills the optimizer slot (`optuna` adapter, built) | which parameters may change and within what bounds; probes as its objective; a verdict on held-out cases before anything is kept |
| **GEPA** (MIT) | evolves anything interpretable as text with model reflection and a Pareto front; you supply the evaluator | would fill the optimizer slot for text cells (planned) | an evaluator out of the candidate's reach (GEPA leaves isolation to you); held-out answers; neighbours' contracts and the system guard |
| **OpenEvolve / AlphaEvolve** (Apache-2.0) | evolves marked code blocks against an evaluator | could fill the optimizer slot for code cells | OpenEvolve imports your evaluator into its own process with no sandbox; Morphogen scores outside the candidate, in a container |
| **AFlow, ADAS, Darwin Gödel Machine** | search over agent workflows or rewrite whole agents against benchmarks | research systems with the same aim at the whole-agent scope | the Darwin Gödel Machine reports objective hacking (an agent removed the signal its checker read); Morphogen's red team and outside measurement exist for exactly that |
| **Kayenta, Argo Rollouts** | judge a canary against a baseline on metrics collected outside the code, after deploy | precedents for the judge, one stage later | judging before merge, on candidates written by an agent that may cheat, with held-out cases and parameter ownership |
| **Kubernetes Horizontal Pod Autoscaler** | changes one setting (replicas) within operator-owned bounds from live metrics | the precedent for a local drive with owned bounds | any cell and modality, structural change, and a judge instead of a fixed rule |
| **Backstage, C4, CycloneDX, SCIP** | describe software at the level of organisations, artifacts or symbols | address spaces a cell's location can point into | cells, parameters with owners, interfaces as tests, and the comparison of intended with observed |
| **graphiti, cognee** | build knowledge graphs from text with model calls | belong to the demos (catalog, ingestion), not the core | a resolver that Morphogen can tune against held-out answers (demos/entity-resolution) |
| **Claude Code, or any coding agent** | builds and changes code | the builder, and the agent that drives Morphogen through its MCP tools | a referee it cannot edit, so its changes are accepted on evidence, not on its own say-so |

## Limits

- The default runner is Podman (`sandbox: auto` picks Podman, then Docker, then none). Without a
  container, code under test runs as you and can read any file you can: naming the private
  directory is refused, but an obfuscated path gets through. In Podman it fails, since only the
  candidate's tree is mounted (a red-team case, run with `MORPHOGEN_TEST_SANDBOX=podman`, where the
  whole suite runs with every trial in a container). A target can insist with `requires: [network_isolated,
  private_paths_hidden, ...]`, and is then refused on a runner without them. Containers use
  `sandbox_image` (default `python:3.12-slim`), so a target's own dependencies must be in that
  image. Bubblewrap, gVisor, Firecracker and remote runners are future options (runner.py).
- The scorer runs without a container: it is the judge's code from the base commit.
- Parameters are read statically; code that changes a setting at run time is the reviewer's to
  catch. TOML keys can be read but not yet written by `tune`.
- The web UI binds to localhost, has no authentication and only reads. It loads Alpine.js 3.17.5
  and Mermaid 12.2.0 (both MIT) from cdn.jsdelivr.net, so the diagram needs network access.
- The evidence log refuses edits through SQLite triggers; whoever can write the file can drop
  them, and the hash chain then shows the edit.
- Optimizer adapters beyond grid and random search (GEPA, Optuna, a Claude Code worker), the
  observed structure from traces, and a selector across cells and scopes are designed in
  BRIEF.md, not built.

## Layout

    morphogen/       the core, its CLI and MCP server
    tests/           its tests and red team, with sample targets in tests/fixtures
    .claude-plugin/  the plugin and marketplace manifests
    skills/, agents/ the Claude Code skill and agents
    demos/       projects Morphogen can build and drive (the core never imports from them)
    BRIEF.md     the design
