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
- [Settings](#settings)
- [Tools](#tools)
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
| **Record** | append the verdicts and the reasons to the journal |

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
- **measure.metrics**: exactly one primary metric, which must be one the judge
  measures itself (`wall_seconds`, `cpu_seconds`, `max_rss_kb`). Numbers the
  workload prints are kept as `reported.*` and can be constraints, never the
  primary metric.

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

## The judge

The judge runs inside the MCP server. The agent can ask it for a score; it
cannot change how scoring works or write measured evidence.

A candidate passes only if all of these hold:

1. it adds no files that shadow standard modules or customise the
   interpreter (`json.py`, `unittest.py`, `sitecustomize.py`, `.pth`);
2. the base's `check` passes on it;
3. its output matches the base's on freshly generated inputs;
4. the primary metric improves by at least its bar, by more than chance
   explains, and no other metric regresses beyond its limit.

How it measures:

- A separate wrapper process runs the workload and reads its resource usage
  from the operating system, so code under test cannot fake its own timing.
- Base and candidate run in paired rounds, alternating which goes first, after
  a warm-up. The median paired gain must clear the bar, and a sign test must
  reject luck at p ≤ 0.01. Close calls get more rounds, up to `max_repeats`.
  In an A/A test (identical code on both sides) this passed 0 of 12 times,
  while a real speed-up passed 5 of 5.
- Seeds are fresh and random for every run and recorded afterwards, so there
  is nothing to read in advance.
- With Docker, every command runs in a container with no network, a read-only
  tree and resource limits.

`server/tests/test_redteam.py` holds known ways to cheat: patching the timer,
printing a fake measurement, rigging or deleting the harness, lowering the bar
in `target.yaml`, shadowing `unittest` or `json` (as a file or a package),
`sitecustomize`, memoising. Every one must fail. A new cheat that passes is a
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

`init_project` seeds them with Morphogen's own map, including its judge, its
backends and its improvement strategies, so Morphogen can treat its own parts
as things to improve. They are JSONL files: commit them with your code.

Behind the lists and the evidence log are ports with a files backend today.
Each backend declares its capabilities (for example whether append-only is
enforced or only tamper-evident), and all must pass the same conformance
tests, so a Postgres backend can be added without changing callers.

## Improvement strategies

`evolve` runs the fixed loop; a **strategy** decides where candidates start
and what to try. Strategies are cards in `strategies/`:

| Strategy | Parent | Good when |
|---|---|---|
| `hill-climb` | the trunk; best of two or three different approaches | one clear bottleneck; the first rounds |
| `archive-search` | promising and under-explored variants from the archive, failures included (after the Darwin Gödel Machine) | hill-climbing has stalled |
| `simplify` | a large pass; smaller versions of it from the trunk (delta debugging) | a pass changes more than it needs to |

`strategy: auto` (the default) chooses from the evidence: hill-climb first;
simplify when a pass that is not merged changes more than 20 lines;
archive-search after four trials in a row without a pass; the strategy with
the best gain per trial once two have a record; stop and report when all have
stalled. Setting a card's name forces it, for the project or per target.

Add your own strategy by writing a card in your project's `strategies/`
directory: Markdown with `name`, `description` and `when` front matter, and
Parent, Candidates, After and Stop sections. `catalogs.yaml` lists more to
write (beam search, islands, reflective evolution, annealing, bandits).

Strategies only propose. None can change the judge, the budgets, or the rule
that a candidate is merged only after it passes against the trunk and you
approve.

## Settings

`morphogen.yaml`, written by onboarding; you own it.

```yaml
trunk: main              # changes only by judged, approved merges
autonomy: 2              # 1 assist · 2 propose · 3 merge free changes · 4 autonomous
data_dir: .morphogen     # lists, journal, traces
strategy: auto           # or hill-climb, archive-search, simplify, or your own card
# strategies:            # per-target overrides
#   targets/slow-script: archive-search
backends:
  default: files
sandbox: auto            # auto (Docker if available) · docker · none
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
| `doctor` | reports the project, backend, evidence chain, sandbox and which guarantees are active |
| `init_project`, `install_sample` | set a project up; copy a sample target in |
| `lists_get`, `lists_put`, `lists_query` | read and write the lists; follow references |
| `evidence_query`, `evidence_note` | read evidence; add an inferred or stated note |
| `catalog_search` | search `catalogs.yaml` and the lists before building |
| `measure` | baseline a target at a commit |
| `judge` | score a candidate against a base; records the verdict |
| `strategy`, `archive`, `strategies_list` | the next strategy and why; judged variants with lineage and payoff; the catalog |
| `journal_append` | append a journal entry |

## Testing and evals

```
cd server
uv run --project . python -m unittest -v tests.test_morphogen tests.test_redteam tests.test_strategies
```

The skills are scored with `claude plugin eval` against a run without the
plugin; see `eval-cases/README.md` for the six cases and the run command.

## Limits

- On a local machine an agent with shell access can reach any file you can.
  The evidence chain makes edits detectable, not impossible. For the strong
  version, run in a container with the plugin mounted read-only, or have CI
  run the judge on pull requests.
- Without Docker, trials run directly on your machine; `doctor` says so.
- The runner uses `sh`, so Windows needs WSL.
- Only the files backend exists so far; Postgres is planned.

## Layout

| Path | What | Portable |
|---|---|---|
| `skills/` | `onboard`, `map`, `evolve`, `playbook` | yes (Agent Skills) |
| `server/` | MCP server, judge, backends, tests | yes (MCP) |
| `strategies/` | improvement strategy cards | yes |
| `samples/` | example config and intent, catalogs, Morphogen's own map, the slow-script target | yes |
| `eval-cases/` | `claude plugin eval` suite | Claude Code |
| `agents/` | `explorer`, `worker`, `reviewer` | Claude Code |
| `hooks/` | session briefing, budget, traces | Claude Code |
| `.claude-plugin/` | plugin and marketplace manifests | Claude Code |
| `harness.yaml` | which parts are portable | |

## License

Apache 2.0. See `LICENSE` and `NOTICE`.
