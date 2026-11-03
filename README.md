# Morphogen

Morphogen maps, measures and improves systems, itself included. It works like
a small platform team, a systems engineer, a data scientist and DevOps,
working for you: you say what counts as better, a judge it cannot edit
decides whether a change is better, and you approve what gets merged.

It ships as a Claude Code plugin: skills for the loop, an MCP server that
holds what Morphogen knows and runs the judge, subagents, hooks, and samples.
Skills, the server and samples are portable to other agent harnesses.

- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [Targets](#targets)
- [The judge](#the-judge)
- [Evidence and trust](#evidence-and-trust)
- [What Morphogen knows: the lists](#what-morphogen-knows-the-lists)
- [Improvement strategies](#improvement-strategies)
- [Runners](#runners)
- [Services and telemetry](#services-and-telemetry)
- [Improving Morphogen itself](#improving-morphogen-itself)
- [Building on Morphogen](#building-on-morphogen)
- [Settings](#settings)
- [Tools](#tools)
- [Admin UI](#admin-ui)
- [Testing and evals](#testing-and-evals)
- [Limits](#limits)
- [Layout](#layout)

## Quick start

Requirements: `git`, [`uv`](https://docs.astral.sh/uv/) and Python 3.11 or
later. Docker is optional; with it, trials run in a networkless container.

In Claude Code:

```
/plugin marketplace add OpenReplicant/morphogen
/plugin install morphogen@morphogen
```

Then, in any git repository:

```
/morphogen:onboard     # set up, agree the intent, optionally install the sample
/morphogen:map         # inventory a target and record its baseline
/morphogen:evolve      # one judged round of improvement; you approve the merge
```

The sample, `targets/slow-script`, is a word-frequency function that is
correct but quadratic. A typical first round finds the bottleneck, tries a few
different fixes on branches, has the judge score each, and proposes the one
that passes, for example around 85% faster with identical output.

## How it works

One loop, the same for every system:

| Step | What happens |
|---|---|
| **Map** | describe the system as slots (roles that could be filled differently) and the components filling them |
| **Measure** | record a baseline with the judge |
| **Catalog** | look for existing parts before writing new ones |
| **Locate** | name the slot that limits the system, with evidence |
| **Source** | reuse, then configure, then compose, then generate |
| **Trial** | build candidates on branches, in parallel, one subagent each |
| **Judge** | score each candidate against the trunk by rules it cannot change |
| **Swap** | propose the winner; you approve the merge |
| **Record** | append the decision to the journal; verdicts and map changes are logged as they happen |

Three crafts guide the work (the `playbook` skill): the data scientist's
(baseline first, several model families, beware leakage and lucky wins), the
systems engineer's (decompose by interfaces, contracts before contents, reuse
before build) and DevOps' (sandbox, small reversible changes, budgets).

Subagents are used for what a separate context gives, not as an org chart:
`explorer` (read-only investigation), `worker` (one candidate per branch and
worktree), `reviewer` (reviews a diff without the author's reasoning).

## Targets

A target is anything Morphogen can trial and the judge can score. It is a
directory with a `target.yaml`:

```yaml
name: slow-script
description: Most frequent words in a text; make it faster without changing results.
interface: direct                 # direct | simulated (see below)

harness: [bench.py, gen.py, test_topwords.py]   # files that belong to the judge

check: python -m unittest -q test_topwords        # must pass on the candidate

equivalence:                      # outputs must match the base on generated inputs
  gen: python gen.py {seed} 3000  # {seed} is fresh and random on every run
  run: python solve.py            # reads the generated input on stdin
  cases: 5

measure:
  run: python bench.py            # the workload; timed from outside the process
  warmup: 1
  repeats: 10
  max_repeats: 30
  metrics:
    wall_seconds: {direction: lower, primary: true, min_improvement: 0.10}
    max_rss_kb:   {direction: lower, max_regression: 0.50}

timeout: 120
```

- **harness**: the benchmark, tests and input generator. The judge takes them,
  and `target.yaml`, from the base commit, so a candidate cannot change how it
  is scored.
- **check**: any command whose exit code means the candidate still works.
- **equivalence**: optional; compares outputs with the base on inputs only
  generated at judging time.
- **measure.metrics**: exactly one primary metric. It must be one the judge
  measures itself (`wall_seconds`, `cpu_seconds`, `max_rss_kb`), or one an
  observer collects outside the code under test (`observed.*`, see
  [Services and telemetry](#services-and-telemetry)). Numbers the workload
  prints are kept as `reported.*` and can be constraints, never the primary
  metric.

To make your own code a target, copy the sample's layout: move the code
under improvement next to a benchmark script, a test file and an input
generator, list those three under `harness`, and pick the metric that matters.

### Direct or simulated

What decides whether Morphogen can work on something is whether it has an
interface to act through: code it can change, a shell, an API. Functions,
libraries, services, test suites and products usually do. So can people and
teams: they can be systems (roles are slots) or components (filling a role
elsewhere), and a swap is an assignment made through whatever system holds it,
such as an HR, ticketing or scheduling API, always with your approval.

When there is no interface to act through, the target is a **simulator**: a
model with its own interface. Declare it:

```yaml
interface: simulated
simulates: the checkout service under production traffic
```

Verdicts on a simulated target get trust `simulated`, not `measured`, and
carry a note: they are evidence about the model, not about reality. Morphogen
never applies such a change to the real system without a direct trial or your
explicit approval. The simulator is a slot of its own and can be improved or
swapped like anything else.

A staging environment is a simulation in this sense: the same code, with
synthetic or replayed traffic instead of real traffic. The direct trial is a
canary or a feature flag: real traffic, limited blast radius. So the path to
production is a pass in simulation, then a pass in a limited direct trial,
then your approval. Progressive-delivery tools such as Argo Rollouts and
Flagger already judge canaries against baseline metrics and roll back; they
are candidates for that slot.

## The judge

The judge runs inside the MCP server. The agent can ask it for a score; it
cannot change how scoring works or write measured evidence.

A candidate passes only if all of these hold:

1. it adds no files that shadow standard modules, customise the interpreter
   (`json.py`, `unittest.py`, `sitecustomize.py`, `.pth`) or shadow a harness
   module (a `gen/` package beside the harness's `gen.py`);
2. the base's `check` passes on it;
3. its output matches the base's on freshly generated inputs;
4. every timed run prints what the base prints on the same input;
5. the primary metric improves by at least its bar, by more than chance
   explains, and no other metric regresses beyond its limit.

How it measures:

- A separate wrapper process runs the workload and reads its resource usage
  from the operating system, so code under test cannot fake its own timing.
- Base and candidate run in paired rounds, alternating which goes first, after
  a warm-up. The median paired gain must clear the bar, and a sign test on
  the untied pairs must reject luck at p ≤ 0.01. Close calls get more rounds,
  up to `max_repeats`. For scores that often tie or can be 0 (a task solved
  or not), set `gain: absolute` and `aggregate: mean` on the metric; a jump
  in success rate from 30% to 70% is then detected about 3 times in 4 within
  30 rounds. In an A/A test (identical code on both sides) the judge passed
  0 of 12 times, while a real speed-up passed (2026-11-02).
- Timing and correctness are checked in the same runs: the harness prints its
  result, and the judge compares each timed run's output (all but the line of
  reported metrics) with the base's. Code that can tell it is being timed
  gains nothing by doing less. A workload whose output varies run to run can
  opt out with `measure.same_output: false`.
- Every round gets a fresh random seed, recorded afterwards, so there is
  nothing to read in advance and nothing one round can learn for the next.
  Without a container, each run of the code under test also gets its own
  empty `TMPDIR` and `HOME`.
- With Docker, every command runs in a container with no network, a read-only
  tree and resource limits.

`server/tests/test_redteam.py` holds known ways to cheat: patching the timer,
printing a fake measurement, rigging or deleting the harness, lowering the bar
in `target.yaml`, shadowing `unittest` or `json` (as a file or a package),
`sitecustomize`, memoising, shadowing a harness module with a package,
behaving differently when the benchmark's environment is set, swapping the
benchmark's input from inside the candidate, caching results on disk across
runs, and tampering with the observer. Every one must fail. A new cheat that passes is a
judge bug: add it there first, then fix the judge.

## Evidence and trust

Everything Morphogen claims is evidence: an append-only log in
`.git/morphogen/evidence.jsonl`. It lives in git's own directory so candidate
commits cannot sweep it up and branch switches cannot lose it; every worktree
shares it. Each record carries the hash of the previous one, so an edit shows
up in `doctor` and in the session briefing.

| Trust | Written by | Means |
|---|---|---|
| `measured` | the judge | measured on the real system |
| `simulated` | the judge | measured on a simulator; about the model, not reality |
| `stated` | the agent | taken from documentation or another source |
| `inferred` | the agent | reasoned, not measured |
| `asserted` | the operator | your say-so |

The agent's own notes (`evidence_note`) can only be `inferred` or `stated`,
and can cite the records they support or challenge.

## What Morphogen knows: the lists

Five lists in `.morphogen/lists/` describe systems, with evidence as the
sixth:

| List | Entry | Refers to |
|---|---|---|
| systems | a whole: a target, a service, a team, Morphogen itself | its slots, its interface |
| slots | a role that could be filled differently | its system, accepted types, interface, what fills it |
| types | a kind of component: hash map, regex, LLM call, simulator | |
| sources | where parts come from: PyPI, the standard library, this project | |
| components | a specific part, with version; can itself be a system | type, source |

`init_project` seeds them with a self-map of four systems, so Morphogen
starts from a worked example instead of a blank page:

| System | Slots | Depends on |
|---|---|---|
| `morphogen` | judge, evidence log, list store, improvement strategy, sandbox, harness, host, admin UI | `claude-code` (harness), `host` (sandbox, Python, git), `admin-ui` |
| `admin-ui` | shell, map viewer, evidence viewer, sessions, terminal, editor | |
| `claude-code` | model, plugins, host | `host`; hosts `morphogen` as a plugin |
| `host` | OS, container engine, Python, git | |

A dependency is a slot filled by a component that is itself a system
(`"system": "claude-code"` on `comp/claude-code`). The host entries are
generic; mapping fills in this machine's actual values. Morphogen can then
treat its own parts, and what it stands on, as things to improve. Every write
to the lists is recorded in the change log (see Storage backends), so the
map's history does not depend on git; commit the lists with your code only if
you want them reviewed alongside it.

### Capabilities and patterns

A slot can say what it `requires` and a component what it `provides`, as
capability names (`exact`, `lexical`, `semantic`, `graph`, `temporal`,
`concurrent-writers`, `enforced-append-only`, ...). `catalog_search` with
`slot:` lists what could fill that slot: components and catalog entries of an
accepted type, those that cover every requirement first, then those missing
the fewest, then those bringing the fewest *extra* capabilities. What the
design does not call for is overhead: the seeded `morphogen/list-store`
requires only exact lookups, so flat files come first; require `graph` too
and the Postgres store moves ahead.

A **pattern** is a system with `pattern: true` and slots that nothing fills:
an architecture to realise, not a running thing, such as "knowledge memory"
(ingest, extract, resolve, invalidate, index, retrieve, store). A concrete
system says `realizes: <pattern>` and each of its slots the pattern slot it
plays, so two products that realise the same pattern can be compared slot by
slot. Patterns belong in a library of their own, mounted as a map
(`patterns:knowledge-memory`), not in each project.

Each requirement should carry its reason, in the slot's `because`
(`{"graph": "evidence:42"}`), so it can be dropped when the reason goes away.
`maps` and `doctor` report, for every slot that requires something:

- **gaps**: what fills it does not provide everything required (a requirement
  was added, or the filler changed). This is where improvement starts:
  `catalog_search(slot=...)` proposes the smallest filler that covers it, and
  the swap is judged like any other change.
- **overhead**: what fills it provides beyond the requirements, a candidate
  for something smaller. Leave a capability out until something requires it.
- **unexplained**: requirements with no reason.

### Several maps

A project's lists are one map. `morphogen.yaml` can mount others, read-only,
so maps kept elsewhere (your home lab, a team's processes, a distribution's
catalog) can be referred to without copying them:

```yaml
maps:
  homelab: {path: ../homelab, commit: 3f2a9c1}       # a git repository, read at a commit
  games:   {git: https://github.com/you/games-map, commit: 3f2a9c1}
  notes:   {path: ../notes/.morphogen/lists}           # a directory, read live (unpinned)
```

A reference into another map is a qualified id: a slot here can be filled by
`homelab:comp/gpu-box`. Bare ids mean the map the entry lives in. A pinned map
is read from git objects at its commit, so later commits or edits in its
repository change nothing here. Entries from a mounted map come back with
`_map` and `_trust: stated` (another map's claim, not checked here). A mounted
map is changed only in its own project, through its own judge; writing to one
from here is refused. The `maps` tool, `doctor` and the admin report list the
mounted maps, whether each is pinned, and any reference, in any map, that does
not resolve.

### Storage backends

Morphogen treats the filesystem like a database: everything goes through
ports, and every backend passes the same conformance tests, so callers do not
change when the backend does. The core asks only for what files can do:

- **the lists**: get, put, query, follow, dump, load;
- **three append-only, hash-chained logs**: `evidence` (claims and
  verdicts), `changes` (every write to the lists: list, id, hashes before and
  after, the new entry, who wrote it and why) and `journal` (decisions:
  gap, options, choice, rung, result, commit).

Anything beyond that is an optional capability that a backend reports and a
slot must require, with a reason. Git versions what you would roll back
(code, targets and harnesses, config, skills, strategy cards); the logs keep
the history of everything else. Two backends exist:

- `files` (the default): one JSONL file per list; the three logs as JSONL in
  git's own directory, untracked, so candidate commits cannot touch them.
  Tamper-evident (hash chains), not enforced.
- `postgres`: for distributions that need a database. Install the driver with
  `uv sync --project server --extra postgres` (pg8000, pure Python).

```yaml
backends:
  default: postgres
  postgres:
    url: postgresql://morphogen@localhost:5432/morphogen   # or MORPHOGEN_POSTGRES_URL
    schema: morphogen
    layout: tables          # tables | labels
```

The two layouts hold the same data. `tables` makes each list a table
(`systems`, `slots`, ...) and adds a `nodes (label, id, data)` view over them;
`labels` stores one `nodes` table with the list as its label and adds a view
per list. Either way, an `edges (src_label, src_id, field, dst_id)` table holds
every reference and is kept in step with each write, so recursive SQL or a
graph extension can walk the map; `follow` is a recursive query. For
[pgGraph](https://github.com/evokoa/pggraph), which indexes existing tables
as a graph, use the `tables` layout: it needs real tables with a
single-column key. The backend's `pggraph_sql()` returns the statements that
register the lists as node tables and `edges` as an edge table labelled by
field (written against pgGraph 1.2's documented API, not yet run against the
extension). `labels` suits tools that want one labelled node table. `catalogs.yaml` is mirrored into a `catalog` table (the file
stays the source). The three logs are tables whose rows a trigger refuses to
update or delete, with the same hash chains, so append-only is enforced, not
only evident; a list write and its change record commit together. `doctor` reports the backend's capabilities, including
`vector_search` when the pgvector extension is installed.

Config, targets and catalogs stay as files in the repository, reviewed with
the code. To move between backends, `dump` from one and `load` into the other.

## Improvement strategies

`evolve` runs the fixed loop; a **strategy** decides where candidates start
and what to try. Strategies are cards in `strategies/`:

| Strategy | Parent | Good when |
|---|---|---|
| `hill-climb` | the trunk; best of two or three different approaches | one clear bottleneck; the first rounds |
| `archive-search` | promising and under-explored variants from the archive, failures included (after the Darwin Gödel Machine) | hill-climbing has stalled |
| `simplify` | a large pass; smaller versions of it from the trunk (delta debugging) | a pass changes more than it needs to |
| `reflect` | the trunk or the best variant; edits aimed at the causes its probe shows (after GEPA, ProTeGi, PromptWizard) | failures that can be read and explained, such as prompts, rules or parsers |
| `tune` | the trunk; settings searched by probe, random first, then narrowing (after random and Bayesian search) | the design is right but its settings may not be |

`strategy: auto` (the default) chooses from the evidence: hill-climb first;
simplify when a pass that is not merged changes more than 20 lines;
archive-search after four trials in a row without a pass; the strategy with
the best gain per trial once two have a record; stop and report when all have
stalled. Setting a card's name forces it, for the project or per target;
`reflect` and `tune` are used that way, or when the `evolve` skill picks them
from `strategies_list`.

Strategies that learn from failures use `probe`: a practice run under the
judge's rules (the base's spec and harness, the forbidden-file check, fresh
inputs) that returns the check's output, each generated case with expected
and actual output where they differ, and a few paired timing rounds. A probe
is recorded as evidence of kind `probe`, never a verdict: it cannot be
proposed for merging, strategy selection ignores it, and it does not count
against `budget.trials_per_day` (`budget.probes_per_day` caps it).

Add your own strategy by writing a card in your project's `strategies/`
directory: Markdown with `name`, `description` and `when` front matter, and
Parent, Candidates, After and Stop sections. `catalogs.yaml` lists more to
write (beam search, islands, annealing, bandits).

Strategies only propose. None can change the judge, the budgets, or the rule
that a candidate is merged only after it passes against the trunk and you
approve.

## Runners

Where the judge's commands run is a slot too. Each runner declares what it
guarantees, and `doctor` reports it.

| Runner | Network | Tree | Limits | Notes |
|---|---|---|---|---|
| `docker` | none | read-only | 1 CPU, 1 GB | needs the Docker daemon |
| `podman` | none | read-only | 1 CPU, 1 GB | rootless, no daemon |
| `none` | yours | writable | none | trials run directly on your machine |

`sandbox: auto` uses Docker, then Podman, then none. Timing is measured
inside the container by the judge's wrapper, so container start-up does not
count. Planned runners are listed in `samples/catalogs.yaml`: Kubernetes Jobs
and Nomad batch jobs for running trials on a cluster, and gVisor or
Firecracker for stronger isolation. A shared cluster makes timings noisier, so
a cluster runner should pin CPUs or use dedicated nodes, or declare its timing
noisy so the judge plans more rounds.

## Services and telemetry

For a target that is a service, the useful metrics are latency, error rate or
cost per request, not process time. The judge gets them through an
**observer**: a harness script it runs after each workload run.

```yaml
measure:
  run: python load.py              # drives the service for this run
  observer:
    run: python observe.py         # queries telemetry for this run, prints JSON
    collected: outside             # outside | self
  metrics:
    observed.p95_ms: {direction: lower, primary: true, min_improvement: 0.10}
    observed.error_rate: {direction: lower, max_regression: 0.0}
```

The workload gets `MORPHOGEN_RUN_ID`, `MORPHOGEN_SIDE` (base or candidate) and
`OTEL_RESOURCE_ATTRIBUTES` tagging its telemetry with both. The observer gets
the same plus `MORPHOGEN_RUN_START` and `MORPHOGEN_RUN_END`, and typically
queries an OpenTelemetry collector, Prometheus, or a proxy's access log for
that run. The observer comes from the base commit, so a candidate cannot
change it.

Trust depends on where the data is collected. `collected: outside` means the
numbers come from something the candidate cannot alter: a load generator's
own view, a sidecar or mesh proxy, eBPF. Only then can an observed metric be
primary. `collected: self` means the service reports on itself through its
own SDK; such metrics can be constraints, never the deciding metric.

Containers have no network, so a service target that sends telemetry needs
`sandbox: none` for now, or a runner with a network to the collector only.

**Morphogen's own telemetry.** Set `OTEL_EXPORTER_OTLP_ENDPOINT` (and
optionally `OTEL_SERVICE_NAME`) in the environment Claude Code starts the
server from, and every `judge` and `measure` call becomes a span with the
target, candidate, strategy, verdict and gains, viewable in a collector,
Jaeger, Grafana or Arize Phoenix. Claude Code can export its own telemetry
over OpenTelemetry too, so the agent's activity and cost can sit beside the
judge's spans. Telemetry never affects a verdict.

## Improving Morphogen itself

Morphogen can improve this repository the same way it improves anything
else. The rule that matters: **the installed plugin is the judge, the
repository is the candidate.**

1. Run Claude Code in a clone of this repository, with the plugin installed
   from the GitHub marketplace (the stable version). Do not add the clone
   itself as a marketplace: the plugin would then run from the clone, and the
   judge would be the candidate.
2. `/morphogen:evolve` builds candidates on branches; workers use worktrees.
   The installed version's server judges them; candidates cannot change it.
3. You approve the merge. Open a pull request: the `judge` workflow re-runs
   the tests, the red-team suite and strategy selection with **main's** tests
   and samples against the candidate's code, outside any agent's reach.
4. Release: bump `version` in `.claude-plugin/plugin.json` and the
   marketplace entry, tag it, then `/plugin update morphogen@morphogen` and
   start a new session. The new version judges only from then on.

Do not point Morphogen at the installed plugin's own directory: that is the
judge editing itself mid-session.

Because the red-team suite is part of what the base uses to judge, a
candidate that weakens the judge fails at least one known cheat. The judge
can get stricter; it cannot quietly get looser.

## Building on Morphogen

Distributions are plugins that depend on Morphogen and add what one kind of
work needs: skills, strategy cards, catalogs, maps, sample targets.
`docs/distributions.md` lists the extension points and the contract the base
keeps stable. Use-case work (assistants, games, business processes) lives in
those repositories, not here. Releases are tagged `morphogen--v<version>`
(see `CHANGELOG.md`).

## Settings

`morphogen.yaml`, written by onboarding; you own it.

```yaml
trunk: main              # changes only by judged, approved merges
autonomy: 2              # 1 assist · 2 propose · 3 merge free changes · 4 autonomous
data_dir: .morphogen     # lists, traces, admin pages
strategy: auto           # or hill-climb, archive-search, simplify, or your own card
# strategies:            # per-target overrides
#   targets/slow-script: archive-search
backends:
  default: files
sandbox: auto            # auto (Docker, then Podman) · docker · podman · none
sandbox_image: python:3.12-slim
budget:
  tool_calls: 0          # per session; 0 means no limit (enforced by a hook)
  trials_per_day: 20     # judge runs per day (enforced by the judge)
targets: [targets/slow-script]
```

`intent.md` holds the purpose, constraints and hard limits in your words. The
skills read it; they change it only with your approval.

## Tools

The MCP server's tools, which any MCP-capable harness can call:

| Tool | Does |
|---|---|
| `doctor` | reports the project, backend, evidence chain, runner and its guarantees, telemetry |
| `init_project`, `install_sample` | set a project up; copy a sample target in |
| `lists_get`, `lists_put`, `lists_query` | read and write the lists (a write can say its `reason`); follow references, across maps |
| `lists_history` | recorded writes to the map: what changed, who wrote it, why |
| `maps` | mounted maps, whether each is pinned, references that do not resolve, capability gaps and overhead |
| `evidence_query`, `evidence_note` | read evidence; add an inferred or stated note |
| `catalog_search` | search `catalogs.yaml` and the lists before building |
| `measure` | baseline a target at a commit |
| `judge` | score a candidate against a base; records the verdict |
| `probe` | a practice run on a candidate: per-case results and quick metrics; never a verdict |
| `strategy`, `archive`, `strategies_list` | the next strategy and why; judged variants with lineage and payoff; the catalog |
| `journal_append` | append a decision to the journal log |
| `admin_pages` | write the admin menu and the read-only report |

## Admin UI

The admin UI is a system in the map like any other: a `shell` slot that lists
what fills the rest (`map-viewer`, `evidence-viewer`, `sessions`, `terminal`,
`editor`). Morphogen fills three of them itself, with static pages written to
`.morphogen/admin/` (ignored by git):

- `index.html`, the menu: what fills each slot, with links that open in new
  tabs;
- `report.html`: the map, the evidence chain's state, each target's archive as
  a lineage tree with each strategy's payoff, and recent evidence.

Write them with the `admin_pages` tool, or outside any agent session:

```
uv run --project server morphogen-admin --project .            # write the pages
uv run --project server morphogen-admin --project . --serve 8765   # and serve them on localhost
```

The pages read and never write. `--serve` is a separate process that answers
GET and HEAD only and binds to 127.0.0.1. All text from the lists and evidence
is escaped, and only http, https and relative links are kept, since the agent
writes those entries. Approvals never go through the admin UI: anything on
the machine, the agent included, can reach a local web page. They stay in the
conversation and in pull requests.

Sessions, terminal and editor are empty until you run a tool for them.
`catalogs.yaml` lists candidates under `admin_ui` (session managers for Claude
Code and Codex, a web terminal, a web editor, a web desktop such as Puter that
could fill the shell slot). Morphogen never installs them. To show one in the
menu, add a component with `status: in use` and its `url`, and fill its slot.

## Testing and evals

```
cd server
uv run --project . python -m unittest -v tests.test_morphogen tests.test_redteam tests.test_strategies
```

The skills are scored with `claude plugin eval` against a run without the
plugin; see `evals/README.md` for the six cases and the run command.

On GitHub, `.github/workflows/judge.yml` runs the tests on every push to main
and judges every pull request with main's tests and samples. Make `judge` a
required status check for main.

To run the suites with trials inside a container, set
`MORPHOGEN_TEST_SANDBOX=docker` (or `podman`). `ContainerGuarantees` checks
that a container runner really has no network, a read-only tree, a memory
limit and nothing kept between runs; it skips engines that are not installed.
In CI this is the `containers` job, started by hand.

## Limits

- On a local machine an agent with shell access can reach any file you can.
  The evidence chain makes edits detectable, not impossible. For the strong
  version, run in a container with the plugin mounted read-only, or have CI
  run the judge on pull requests.
- Without Docker or Podman, trials run directly on your machine; `doctor`
  says so.
- Containers have no network, so service targets that send telemetry run
  with `sandbox: none` for now.
- The runner uses `sh`, so Windows needs WSL.
- On the files backend, append-only is tamper-evident, not enforced; the
  postgres backend enforces it.
- No model gateway yet: a target that calls an LLM needs `sandbox: none`, its
  token cost is not measured from outside, and `budget.trials_per_day` caps
  trials, not spending (#43).
- Between trials the judge resets inputs (a fresh seed every round) and, without
  a container, temporary and home directories; it does not yet reset other
  state a target keeps on purpose, such as an agent's memory (#45).
- `morphogen-admin --serve` has no authentication; it binds to localhost and
  serves read-only pages.
- An unpinned mounted map is read live; pin maps you depend on.

## Layout

| Path | What | Portable |
|---|---|---|
| `skills/` | `onboard`, `map`, `evolve`, `playbook` | yes (Agent Skills) |
| `server/` | MCP server, judge, backends, tests | yes (MCP) |
| `strategies/` | improvement strategy cards | yes |
| `samples/` | example config and intent, catalogs, the self-map, the slow-script target | yes |
| `evals/` | `claude plugin eval` suite | Claude Code |
| `agents/` | `explorer`, `worker`, `reviewer` | Claude Code |
| `hooks/` | session briefing, budget, traces | Claude Code |
| `.claude-plugin/` | plugin and marketplace manifests | Claude Code |
| `.github/workflows/judge.yml` | judges pull requests with main's tests | GitHub |
| `docs/` | building distributions, related work | yes |
| `harness.yaml` | which parts are portable | |

## License

Apache 2.0. See `LICENSE` and `NOTICE`.
