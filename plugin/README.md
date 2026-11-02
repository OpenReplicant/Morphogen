# Morphogen

Maps, measures and improves systems, itself included. Minimum viable version,
packaged as a Claude Code plugin.

Morphogen works like a small platform team, a systems engineer, a data
scientist and DevOps, working for you. You say what counts as better; a judge
it cannot edit decides whether a change is better; you approve what gets
merged.

## Install

Requirements: `git`, [`uv`](https://docs.astral.sh/uv/) and Python 3.11+.
Docker is optional; with it, trials run in a networkless container.

```
/plugin marketplace add OpenReplicant/morphogen
/plugin install morphogen@morphogen
```

Then, in a git repository:

```
/morphogen:onboard
```

## Try it on the sample

Onboarding can install `targets/slow-script`: a word-frequency function that
is correct but quadratic, with tests, a benchmark and an input generator that
belong to the judge.

```
/morphogen:map      # inventory it and record the baseline
/morphogen:evolve   # try several faster versions on branches; the judge scores each
```

The judge passes a candidate only if the trunk's tests pass on it, its output
matches the trunk on freshly generated inputs, and it is at least 10% faster,
timed from outside the process, by more than chance explains. You approve the
merge.

## Improvement strategies

`evolve` runs a fixed loop (locate, build candidates, judge, review, propose,
record). What to try is decided by a **strategy**, chosen from a catalog of
cards in `strategies/`:

| Strategy | Parent | Good when |
|---|---|---|
| `hill-climb` | the trunk; best of two or three different approaches | one clear bottleneck; the first rounds |
| `archive-search` | promising and under-explored variants from the archive, failures included (after the Darwin Gödel Machine) | hill-climbing has stalled |
| `simplify` | a large pass; smaller versions of it from the trunk (delta debugging) | a pass changes more than it needs to |

`strategy: auto` (the default) chooses from the evidence: hill-climb first;
simplify when a pass that is not merged changes more than 20 lines; switch to
archive-search after four trials in a row without a pass; prefer the
strategy with the best gain per trial once two have a record; stop and report
when all have stalled. Set a card name to force one, per project or per
target. Add your own cards in your project's `strategies/` directory; the
catalog in `catalogs.yaml` lists more strategies to write as cards (beam
search, islands, reflective evolution, annealing, bandits).

Strategies only propose. None of them can change the judge, the budgets, or
the rule that a candidate is merged only after it passes against the trunk
and you approve. `archive(target)` shows every judged variant with its
lineage, and the payoff of each strategy.

## What is in the plugin

| Part | What it does |
|---|---|
| `skills/` | `onboard`, `map`, `evolve`, `playbook` |
| `server/` | MCP server: lists, evidence, catalog search, `measure`, `judge`, `strategy`, `archive`, journal, `doctor` |
| `strategies/` | improvement strategy cards: `hill-climb`, `archive-search`, `simplify` |
| `agents/` | `explorer` (read-only), `worker` (one candidate per branch), `reviewer` (blind review) |
| `hooks/` | session briefing, optional tool-call budget, traces |
| `samples/` | example config and intent, catalogs, Morphogen's own map, the slow-script target |

`harness.yaml` marks which parts are portable (skills, MCP server, samples)
and which are specific to Claude Code (manifest, hooks, subagents).

## What Morphogen keeps

- **Lists** (`.morphogen/lists/`): systems, slots, types, sources and
  components. What is known about each system, as JSONL you can read and diff.
- **Evidence** (`.git/morphogen/evidence.jsonl`): claims with their support.
  The judge writes `measured` records; the agent can only add `inferred` or
  `stated` notes. Each record carries the hash of the previous one, so edits
  show up. It lives in git's own directory so candidate commits cannot sweep
  it up and branch switches cannot lose it; every worktree shares it.
- **Journal** (`.morphogen/journal.md`): why each change was made.

Commit the lists and journal with your code. Traces are ignored.

## Guarantees, stated plainly

`doctor` reports which of these are active.

| Guarantee | How |
|---|---|
| A candidate cannot change how it is scored | the judge reads `target.yaml` and harness files from the base commit |
| Timing cannot be faked by the code under test | a separate wrapper process times the run and reads its resource usage; printed numbers are only "reported" |
| No tuning to the benchmark | fresh random seeds every judge run; nothing stored to read in advance |
| No interpreter tricks | candidates may not add files that shadow standard modules, `sitecustomize`, or `.pth` files |
| No lucky wins | warm-up; paired rounds in alternating order; the median paired gain must clear the bar and a sign test must reject luck at p ≤ 0.01; more rounds on close calls. Identical code passed 0 of 12 times in an A/A test |
| Trial budget | `budget.trials_per_day` enforced by the judge |
| Measured evidence only from the judge | the agent's tool writes `inferred` or `stated` only |
| Evidence edits are detectable | hash chain, checked by `doctor` and the session briefing |
| Trials isolated | only with Docker (`sandbox: docker`); otherwise trials run directly |

`server/tests/test_redteam.py` holds known cheats (patching the timer,
printing fake measurements, rigging or deleting the harness, lowering the
bar, shadowing `unittest` or `json`, `sitecustomize`, memoising). Every one
must fail; a new cheat that passes is a judge bug.

On a local machine an agent with shell access can reach any file you can.
For the strong version, run in a container with the plugin mounted
read-only.

## Not yet

Postgres backend (the ports are defined; files are implemented), more target
types, the event bus and workspace, the JIT compiler for LLM calls, and other
harnesses.

## Develop

```
cd server
uv run --project . python -m unittest -v tests.test_morphogen tests.test_redteam tests.test_strategies
```

Apache 2.0.
