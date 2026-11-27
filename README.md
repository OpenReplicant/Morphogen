# Morphogen

**A kit for improving a system, with a judge at its core.** Morphogen **maps** a system (what it is made of, the
role each part plays, the interfaces that make parts interchangeable), **researches and catalogues** the options
for each role, and **optimises** behind a judge: point any optimizer or coding agent at part of the system (a
prompt, a setting, a function, a skill, a service) and the judge decides whether the change is really better, by
rules taken from the last approved version, with measurements taken outside the code, on cases the optimizer
never saw, without breaking a neighbour or making the whole system worse. Every verdict goes into a log that
cannot be quietly edited.

It works on files only, on any harness that reads Agent Skills: the map and the catalog are Backstage catalog
entity files in your repository (no database, no server), the documentation of an option is markdown files, and
the judge is a Python package with an MCP server. The Claude Code plugin is the first packaging; other
harnesses get a thin manifest over the same core and skills.

**The judge stays the core, and stays independent.** The mapping and cataloguing skills write the map and the
catalog, which the judge reads from the base commit and no candidate may touch: what an optimizer may edit is
still only what a cell's `change` names. Morphogen does not propose changes itself; optimizers do that, and they
plug into it. [BRIEF.md](BRIEF.md) is the design (its first section is
the one-page version) and [PLAN.md](PLAN.md) the way there; this file is the case for Morphogen and
how to use what is built.

**Where it sits.** The Knowledge Kernel is an optional layer above the kit: it ingests the same Backstage files for
indexing, search and graph traversal, and the kit never requires it. Substrate is the default distribution (a
configured harness, the kernel and a default stack) and installs Morphogen's plugin like any user. MetaSoar's
System 1 skills convention (policies, observers and cases in a skill folder, each a Morphogen cell) is a planned
consumer of the judge. The way there is [PLAN.md](PLAN.md).

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

Everything committed is a Backstage catalog. The project's catalog root is `catalog-info.yaml` at the
repository root; it may be a `Location` whose `targets` name more files inside the project. Morphogen's own
fields go under one key, `spec.morphogen`, on the entity they are about (the fields are in
[`schemas/morphogen-spec.v1.json`](schemas/morphogen-spec.v1.json)):

| On | `spec.morphogen` holds |
|---|---|
| the entity a cell judges (Component, System, Domain, AiResource) | the cell's rules: `change`, `keep`, `run`, `better`, `tests`, `score`, ... (below). An entity with no `run` (and no tests) is structure, not a judged cell |
| a sub-grain cell | the same, on a `Component` of its own nested with `spec.subcomponentOf` |
| an `API` | the interface's `tests`, and `external: consumes` or `provides` when the code needs it |
| the `System` | the project's settings (`trunk`, `sandbox`, `sandbox_image`, `budget`, `autonomy`) and `defaults`: cell fields every cell with rules in that System inherits unless it sets its own (a field set to `null` opts out). At most one System carries settings; two is an error |
| an option for a role (`spec.lifecycle: candidate`) | `fills`, `parameters`, `licence`, `docs`, `evaluation` (the `catalog` skill). An option, and a role (`spec.type: role`), is never a cell |

What Backstage already says is not repeated: `in` is `subcomponentOf` (or `system`, `domain`, `subdomainOf`),
`provides` and `consumes` are `providesApis` and `consumesApis` (and `dependsOn`), `owner` and `lifecycle` are the
entity's own. A cell is named by its `metadata.name` (`namespace/name` outside the `default` namespace), so two
cell entities may not share a name; a ref in any spelling (`classify`, `component:classify`,
`component:default/classify`) names it.

A complete project, `catalog-info.yaml`:

```yaml
apiVersion: backstage.io/v1alpha1
kind: System
metadata: {name: app}
spec:
  owner: team-a
  morphogen:
    sandbox: podman                           # settings: from the base commit, like every rule
    budget: {trials_per_day: 20}
    autonomy: {experimental: merge}           # lifecycle -> may an agent merge a pass (default: review)
    defaults:                                 # inherited by every cell below that sets none of its own
      rounds: {warmup: 0, repeats: 4, max_repeats: 8}
      timeout: 60
---
apiVersion: backstage.io/v1alpha1
kind: Component
metadata: {name: classify}
spec:
  type: service
  lifecycle: experimental                     # what `autonomy` keys on
  owner: team-a                               # who approves its candidates
  system: app                                 # `in`
  providesApis: [labels]
  morphogen:
    dir: classify                             # where its commands run (default: the root)
    change: classify/classify.py#THRESHOLD in 0..100   # what may change; nothing else may
    run: python bench.py                      # the workload
    better: accuracy higher                   # the primary metric and its direction
    score: python score.py                    # scores each run's output, from the base
    tests: python -m unittest -q test_classify   # must pass; a failure refuses
---
apiVersion: backstage.io/v1alpha1
kind: Component
metadata: {name: threshold}                   # below the grain of the part: its own cell, nested
spec:
  type: library
  subcomponentOf: classify                    # `in`
  morphogen:
    change: classify/classify.py#THRESHOLD in 0..100
    run: python bench.py
    better: wall_seconds lower
---
apiVersion: backstage.io/v1alpha1
kind: Component
metadata: {name: report}
spec: {type: service, system: app, consumesApis: [labels]}   # structure: no morphogen, no run
---
apiVersion: backstage.io/v1alpha1
kind: API
metadata: {name: labels}
spec:
  type: openapi
  definition: labels.yaml
  morphogen:
    tests: python -m unittest -q contracts.test_labels   # run from the root
---
apiVersion: backstage.io/v1alpha1
kind: Component
metadata: {name: rapidfuzz}                   # an option for a role: never a cell
spec:
  type: library
  lifecycle: candidate
  morphogen: {fills: matcher, licence: MIT}
```

Every catalog file the judge reads (the root and each `Location` target) is a rule file, read from the base
commit only: a candidate that changes, adds or removes one is refused, whatever `change` says, so a candidate
cannot edit the rules it is judged by. A catalog file the root does not reference is not read and is not
a rule file.

- **Default deny.** A candidate may change only what the judged cell's scope names in `change`.
  Anything else changed, the catalog files, the bench, the scorer and every test included, refuses
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
  Verdicts score against `private`; probes, and so every optimizer, against `search`. A scorer
  should also print `cases_seen` (the cases it found in the run's output) and `cases_expected` (the
  answers it holds) beside its metrics: when they differ the judge refuses a candidate's run, and
  refuses to judge at all when the base's run is the short one. A workload whose last line of output
  is a JSON line loses that line (it is kept as what the run reports about itself, not passed to the
  scorer), so end the workload on a closing line. Data the
  workload reads but that cannot be committed (a licence, its size) is named the same way as
  `inputs`: every run reads it from `MORPHOGEN_INPUTS`, a container mounts it read-only, and the
  judge refuses a verdict if it changed during the runs. It must lie outside the repository and
  away from the answers. The local file may also set `sandbox` and `budget`.
- **Services and settings a run needs** (a database, values from an env file) are the operator's too,
  named in the same file:
  `env: {file: /outside/run.env, pass: [DATABASE_URL], public: [DB_PORT]}` and
  `services: {db: {image: docker.io/library/postgres:17.6, env: [POSTGRES_PASSWORD], ready: pg_isready}}`.
  Every run gets the `pass` values as environment variables; in a container each run gets its own fresh
  services, reached by name on a network with nothing else on it. The verdict records the names, one
  digest of the values and each image's id, never a value; a run that prints a secret value is refused
  (`morphogen/serve.py`).
- **Model calls are counted at the gateway, not by the candidate.** `gateway: {container: my-gateway,
  port: 8080, meter: /outside/meter}` names the operator's running gateway and a meter. Each run's
  network then holds the gateway too (as `gateway`, at `MORPHOGEN_GATEWAY`), and nothing past it. The
  meter runs outside the candidate: `meter open RUN_ID` prints `{"env": {...}}` (the key the run calls
  with), `meter close RUN_ID` prints that run's counts from the gateway's own record (`{"calls": 3,
  "tokens": 120, "cost": 0.0}`). They are `metered.*` metrics a cell's `better` can name, primary
  included; what a run prints about its own calls stays `reported.*` and decides nothing. A number the
  judge measured that `better` does not name (the meter's other counts, the judge's own timings) is kept in the
  verdict as `outcome.recorded`, each side's median, for the record: it decides nothing, and no `reported.*`
  number is kept there.

Name a cell to judge as `cell:classify`, `classify`, or its `dir`. A project with nothing yet starts
with one cell; the `map` skill drafts it with you.

**A change that claims no improvement** (a fix, a new part, a refactor) has no measure to judge, but
it can still break what other parts rely on. `morphogen change BRANCH` judges it by the base's rules
without a target: the cells it belongs to come from the files it changes (each cell whose `change`
covers a file), every changed file must belong to one (default deny, so the rules and files no cell
claims never change), and the cells' own tests, with the tests of every interface their scopes touch
or their enclosing systems' boundaries cross, must pass on the candidate. That is the blast radius,
computed from the structure rather than declared. The result is recorded as a verdict on the change,
with the same `gate` (who may merge it) as any other.

### How the catalog maps to cells

| Backstage | Becomes |
|---|---|
| `Component`, `System`, `Domain` | a cell, named by its name (`namespace/name` outside `default`) |
| `AiResource` (Backstage 1.51: skills and rules) | a cell, `in` its `system`; a skill named in `change` is a text cell |
| `owner`, `lifecycle` | the cell's `owner` (who approves its candidates) and `lifecycle` (what `autonomy` keys on) |
| `subcomponentOf`, `system`, `domain`, `subdomainOf` | `in` |
| `API` | an interface; its tests are `spec.morphogen.tests` |
| `providesApis`, `consumesApis` | `provides`, `consumes` |
| `dependsOn` | consumes it: provided by that cell, or external (a `Resource`) |
| `Location` targets | more catalog files to read, and so more rule files |

The catalog is read directly, with no Backstage server. `structure check` reports which file each cell and
interface came from.

**Who may merge a pass.** The judge never merges. Each verdict carries a `gate`: the cell's owner
and lifecycle, and the decision, `review` (a person decides) unless the System's `autonomy`
lets an agent merge a pass for that lifecycle (`autonomy: {experimental: merge}`).
The gate is read from the base, so a candidate that relabels its cell `experimental`, or grants
itself autonomy, is refused like any other edit to the rules. `demos/entity-resolution` is
described this way: one `catalog-info.yaml`, its `er` System carrying the F1 workload as `defaults`.

## In Claude Code

```
/plugin marketplace add OpenReplicant/Morphogen
/plugin install morphogen@morphogen
```

Install it from GitHub, not from a local clone: a clone added as a marketplace runs the plugin from
the clone itself, so the judge would be the candidate you are changing. To move to a newer version,
`/plugin marketplace update morphogen`, then `/plugin update morphogen@morphogen`, and restart
Claude Code. The plugin brings the MCP server, four skills (`map`: take a system apart into Backstage entity files with
evidence and draft its cells; `catalog`: find options for a role; `research`: choose one from the catalogs;
`morphogen`: improve a cell honestly), and the `worker` and `reviewer` agents. It needs
[uv](https://docs.astral.sh/uv/) on the path.

**Starting fresh.** In a git repository, ask Claude to start Morphogen here. The map skill calls
`status`, which says where the project stands and the next step: no commit yet, no map, a map
drafted but not on `main`, a cell the judge cannot judge yet (and why), a cell to measure, a cell
to improve. It reads the project's `catalog-info.yaml`; where one exists without Morphogen's fields, it adds `spec.morphogen` and leaves the rest. The first map is one cell,
the part you want improved, with what may change, how to run it, what "better" means and the tests
it must keep passing; it reaches `main` by your pull request, and only then does a verdict rest on
it.

## From the command line

```
uv sync
uv run morphogen status                         # where the project stands; the next step
uv run morphogen structure check catalog-info.yaml
uv run morphogen measure cell:classify
uv run morphogen judge cell:classify my-branch
uv run morphogen change my-branch                # a change that claims no improvement: its cells' tests
uv run morphogen request /outside/request.yaml   # one document: what to judge, and the operator's settings
uv run morphogen pr --base main --head HEAD --sandbox podman --local /outside/morphogen.local.yaml --out v.json
                                                 # a pull request, as the GitHub judge runs it
uv run morphogen tune cell:classify              # the selector chooses optimizers
uv run morphogen optimizers                      # the catalog
uv run morphogen evidence --verify
uv run morphogen ui                              # http://127.0.0.1:8765/
```

### A request: one document in, one verdict out

A system that calls the judge can say everything it passes in one file, kept outside the repository:

```yaml
morphogen: request/v1
kind: judge                     # judge | change | probe | measure
project: /path/to/the/repository
base: main
candidate: my-branch
target: cell:classify
labels: {optimizer: grid}       # recorded, never decide
local:                          # optional: replaces morphogen.local.yaml
  sandbox: podman
  cells: {classify: {private: /outside/answers, search: /outside/search, inputs: /outside/data}}
  env: {file: /outside/run.env, pass: [DATABASE_URL]}
  services: {db: {image: docker.io/library/postgres:17.6, env: [POSTGRES_PASSWORD]}}
  gateway: {container: my-gateway, port: 8080, meter: /outside/meter}
```

The rules (cells, interfaces, tests, and the System's settings in the catalog) still come from the base commit:
a request that carries any, or sits inside the repository, is refused. The verdict records the request's
digest. Each record in the evidence log follows a published schema,
[`schemas/evidence-record.v1.json`](schemas/evidence-record.v1.json) (generated from `morphogen/schema.py`,
which also says how to verify the hash chain without Morphogen's code).

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
| Cell format | `project.py`, `backstage.py` | reads the catalog (`catalog-info.yaml` and the Location targets it names); compiles it to a structure and, per cell, the spec the judge runs; default deny |
| Structure | `structure.py`, `render.py` | cells in a containment tree, interfaces as hyperedges with their tests; checks, scopes, computed boundaries, intent coverage, intended against observed, a Mermaid diagram |
| Judge | `judge.py`, `runner.py` | scores a candidate commit against a base by the base's rules; `judge_change` holds a change with no measure to the tests of what it touches; `probe` gives practice feedback; `measure` records a baseline |
| Evidence | `evidence.py` | an append-only, hash-chained log of measured and stated claims, in git's own directory |
| Observers | `observers.py` | `command` (a command after each run) and `otel` (an OpenTelemetry receiver in the judge that adds up each run's telemetry, such as Claude Code's cost, tokens and tool results) |
| Optimizers | `optimize.py` | a catalog behind one contract: grid, random, hill-climb (with `restarts`) and simulated annealing (`anneal`), built in; Optuna and GEPA adapters (optional extras); and the `selector`, whose bandit policy (primed by earlier verdicts, with a stagnation signal) chooses which proposes next. A model-based policy is planned; packages add more through the `morphogen.optimizers` entry point. `tune` checks, writes and probes each proposal and judges the best |
| Interfaces | `cli.py`, `mcp_server.py`, `ui.py` | the command line, an MCP server with 13 tools, and a local read-only web UI |
| Plugin | `.claude-plugin/`, `skills/`, `agents/` | the Claude Code plugin around the MCP server; the skills (`map`, `catalog`, `research`, `morphogen`) are plain Agent Skills any harness can load |
| Schemas | `schemas/` | the evidence record (v1); the `spec.morphogen` fields of the catalog entities the code loads (v1; a test keeps them equal); the research loop's evidence claim (v1, draft) |

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

## A judge the author cannot reach

When a coding agent writes the candidates, the held-out answers must be out of the agent's reach, not
only the candidate's. On one machine that means a second Unix user, the judge, whose home the author
cannot read:

```
/var/lib/morphogen-judge/          # mode 700
  venv/                            # Morphogen, installed from GitHub main: not the author's copy
  projects/myproject/              # the judge's own clone; verdicts go into its evidence log
  requests/myproject.yaml          # a request with no candidate: project, base, target, private paths
  private/myproject/               # the held-out answers
```

The author may run one thing as that user, through a `sudoers` rule that needs no password, and
hands the candidate over as a git bundle:

```
git bundle create - my-branch ^main | sudo -u morphogen-judge /usr/local/bin/morphogen-intake myproject
```

`morphogen-intake` is a two-line script owned by root that runs `morphogen intake judge NAME` from
the judge's install. The author gives a name and a bundle and gets the verdict. It never names a
path, a base or a rule; the bundle lands outside the judge's branches, and nothing of it stays.

The base branch of the judge's clone moves only with `morphogen intake advance NAME`, which reads
the new base as a bundle the same way and only goes forward. Leave it out of the `sudoers` rule, so
it takes the owner's password: an author who could move the base could commit weaker rules, call
that commit the base and be judged by them.

Rootless Podman keeps images and containers per user, so the judge needs the sandbox image, any
service images and its own model gateway in its own store.

## On GitHub: the judge as a reusable workflow

`.github/workflows/judge.yml` judges every pull request into your main branch by the catalog on main. Your repository
needs only `catalog-info.yaml`; the operator's private material (a `morphogen.local.yaml` naming the held-out answers,
inputs, env file and services, with the directories it names) lives in a private repository the workflow clones
outside your checkout. Call it from a `pull_request_target` workflow, so the definition that runs is main's:

```yaml
name: morphogen
on:
  pull_request_target:
    branches: [main]
    types: [opened, synchronize, reopened, edited]
permissions: {}
jobs:
  judge:
    uses: OpenReplicant/Morphogen/.github/workflows/judge.yml@COMMIT   # pin by commit
    permissions: {contents: read, statuses: write, id-token: write}
    secrets: inherit                                # MORPHOGEN_CASES_TOKEN, and the App's keys with verdict-poster: app
    with:
      judge-ref: COMMIT                             # the same commit
      cases-repo: you/your-judge-material           # holds DIR/morphogen.local.yaml and what it names
      cases-dir: your-project                       # paths in that file are relative to it
      protected: ".github/** .morphogen/**"         # beyond the catalog files, which are always refused
      sandbox: docker                               # or podman; never none
      verdict-poster: app                           # or actions
```

The `judge` job holds only a read token. It fetches main and the pull request's head as git objects (nothing of the
candidate is checked out by the workflow), installs the judge at `judge-ref` from hash-locked wheels
(`requirements.lock`, exported from `uv.lock`), clones the private material, and runs `morphogen pr`, which hands the
judge a request (above) and so keeps every rule it keeps: the rules from main as it is now (a branch behind main is
judged merged onto it), a candidate that changes a catalog file or `morphogen.local.yaml` refused, every candidate
command in a container with no network that sees only the candidate's tree, the answers given only to main's scorer.
A pull request that touches no file any cell may change, and no rule file, is a pass (not judged); one that touches a
`protected` path is refused. Name the cell to judge with a line `morphogen-target: cell:NAME` in the pull request's
description; without one, the change is judged as one that claims no improvement (`morphogen change`). The `post`
job signs the verdict (Sigstore, keyless by default), posts `morphogen/verdict` on the head commit and keeps the
verdict and the run's evidence records as artifacts; a judge that fails is posted as a stop, never a pass.

**On GitHub, only the container keeps the answers from the candidate.** The `judge` job clones the private material
into the runner's temporary directory, on the same virtual machine where the candidate's commands run. A candidate
cannot read it because its container mounts only the candidate's tree, read-only, with no network. Nothing else
stands between them: the containers run as the image's user (root, for `python:3.12-slim`) under the runner's Docker
daemon, with Docker's default capabilities, so a container escape would reach the answers and anything else on the
runner. The rebuild-8 judge that the dogfood caller still pins (`b921c9b`) ran candidates in a job that never had
the answers on disk. The trade-off is open (see "Limits").

## What the judge guarantees

- **The rules are the base's.** The catalog files and everything a cell's `change` does not name come
  from the base commit; a candidate that changes any of it is refused before anything runs.
- **Measurement is outside the code.** Time and memory are measured by a wrapper process; inputs
  come from a fresh seed every round; each timed run must print what the base prints (unless the
  output is scored, or `same_output: false`). Numbers the workload prints are kept as `reported.*`
  and never decide a verdict.
- **Answers are out of reach.** The base's scorer runs in its own process; only it is told where
  the held-out answers are (`MORPHOGEN_PRIVATE`); probes score against `search` instead; a
  candidate whose files name the private directory is refused. Inputs kept outside the repository
  are read-only to every run, and their digest is in every verdict.
- **Values and services do not leak or carry over.** Env values come from a file outside the commits
  (refused if git tracks it), read once and checked again after the runs; a run whose output holds a
  secret value, as it is or in base64, hex or reversed, is refused before its output is kept. Services
  start from a fixed image id, fresh for each run, on an internal network: no route to the host or
  the internet, and nothing one run writes there reaches the next.
- **Model calls are counted where the candidate cannot reach.** With a gateway named, a run's only route
  out is the gateway; a call around it has nowhere to go, and a call with a key of the candidate's own is
  the gateway's to refuse. Each run's calls, tokens and cost come from the operator's meter reading the
  gateway's record; the key the meter gives a run is scanned for in its output like any secret.
- **The judge's own settings are the base's too.** The sandbox, its image and the budget come from
  the catalog's settings as committed on the base, with only the operator's `morphogen.local.yaml` (or a
  request's `local`) over them, never from the working copy; each verdict records them and where each
  came from.
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

The red team holds the known ways to cheat: 61 of them (`tests/test_redteam.py` and the default-deny
cheats in `tests/test_cells.py`), from patching the timer to reading the held-out answers, rigging
the bench, widening `change` in the candidate's own catalog, breaking a neighbour's
contract, winning locally while the system gets slower, switching telemetry off to look free, raising
the budget in an uncommitted working copy, or carrying rules in a request.
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

- **An agent on your machine runs as you.** A container keeps the held-out answers from the candidate's
  code, not from the agent that wrote it: that agent can read `morphogen.local.yaml` and open the
  directory it names. Cases the agent must not see belong to another user or another machine; see
  "A judge the author cannot reach".
- **Without a container, code runs as you.** It can read any file you can: naming the private
  directory is refused, but an obfuscated path gets through. In Podman it fails, since only the
  candidate's tree is mounted. `sandbox: auto` picks Podman, then Docker, then none; a cell can
  insist with `requires: [network_isolated, private_paths_hidden, ...]`. Containers use
  `sandbox_image` (default `python:3.12-slim`), so a cell's dependencies must be in that image.
- **The scorer runs without a container**: it is the judge's code from the base commit.
- **On GitHub, the held-out answers share the runner with candidate code.** Container isolation (no network, only
  the candidate's tree mounted) is the only thing between them; the containers are not hardened further (no
  `--cap-drop`, no `no-new-privileges`, root inside). Keep cases the candidate must never see on a judge it cannot
  reach ("A judge the author cannot reach"), or accept that a container escape on the runner would expose them.
- **Settings are read statically.** Code that changes a setting at run time is the reviewer's to
  catch. TOML keys can be read but not yet written by `tune`.
- **Default deny is as narrow as `change`.** `change: "**"` would open everything but the project
  file; keep each cell's `change` to what it should touch.
- **The web UI** binds to localhost, has no authentication and only reads. It loads Alpine.js 3.17.5
  and Mermaid 12.2.0 (both MIT) from cdn.jsdelivr.net, so the diagram needs network access.
- **The evidence log** refuses edits through SQLite triggers; whoever can write the file can drop
  them, and the hash chain then shows the edit.
- **Backstage is read from files only:** `$text`, `$json` and `$yaml` substitutions, URL targets and
  the catalog's REST API are not read. A live catalog could change during a search, so if it is
  ever read, it will be as a snapshot whose hash the evidence records; verdicts would flow back to
  it, not rules from it.
- **GEPA's model calls are not sandboxed by the judge:** they run as you, through the Claude CLI,
  with tools switched off. What the model proposes can only be written into the cell's own files.
- **Not built yet:** the observed structure from traces, verdicts published back to Backstage, and
  the online stage ([PLAN.md](PLAN.md)).

## Layout

    morphogen/       the core, its CLI, MCP server and web UI
    tests/           its tests and red team; fixture projects in tests/fixture*.py
    .claude-plugin/  the plugin and marketplace manifests
    skills/, agents/ the skills (Agent Skills format) and Claude Code agents
    schemas/         published JSON Schemas (evidence record, spec.morphogen, evidence claim)
    demos/           projects Morphogen can build and drive (the core never imports from them)
    BRIEF.md         the design;  PLAN.md  the way there
