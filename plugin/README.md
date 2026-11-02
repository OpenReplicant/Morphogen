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
matches the trunk on hidden inputs, and it is at least 10% faster on a
benchmark seeded by a value only the judge knows. You approve the merge.

## What is in the plugin

| Part | What it does |
|---|---|
| `skills/` | `onboard`, `map`, `evolve`, `playbook` |
| `server/` | MCP server: lists, evidence, catalog search, `measure`, `judge`, journal, `doctor` |
| `agents/` | `explorer` (read-only), `worker` (one candidate per branch), `reviewer` (blind review) |
| `hooks/` | session briefing, optional tool-call budget, traces |
| `samples/` | example config and intent, catalogs, Morphogen's own map, the slow-script target |

`harness.yaml` marks which parts are portable (skills, MCP server, samples)
and which are specific to Claude Code (manifest, hooks, subagents).

## What Morphogen keeps

- **Lists** (`.morphogen/lists/`): systems, slots, types, sources and
  components. What is known about each system, as JSONL you can read and diff.
- **Evidence** (`.morphogen/evidence.jsonl`): claims with their support. The
  judge writes `measured` records; the agent can only add `inferred` or
  `stated` notes. Each record carries the hash of the previous one, so edits
  show up.
- **Journal** (`.morphogen/journal.md`): why each change was made.

Commit the lists, evidence and journal with your code. Traces are ignored.

## Guarantees, stated plainly

`doctor` reports which of these are active.

| Guarantee | How |
|---|---|
| A candidate cannot change how it is scored | the judge reads `target.yaml` and harness files from the base commit |
| No tuning to the benchmark | hidden seeds, stored outside the project |
| Measured evidence only from the judge | the agent's tool writes `inferred` or `stated` only |
| Evidence edits are detectable | hash chain, checked by `doctor` and the session briefing |
| Trials isolated | only with Docker (`sandbox: docker`); otherwise trials run directly |

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
uv run --project . python -m unittest -v tests.test_morphogen
```

Apache 2.0.
