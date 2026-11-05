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
- Every verdict and probe is evidence: `trust: measured, by: judge`.

`tests/test_redteam.py` holds the known ways to cheat: 26 of them, from patching the timer to
reading the held-out answers. Every one must fail; a new one that passes goes there first.

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
