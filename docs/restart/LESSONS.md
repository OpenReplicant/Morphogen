# Lessons from Morphogen 0.1 to 0.3

What this repository taught, for the project that replaces it. Each lesson names where it came
from.

## The judge

- **The optimizer must not control the measure.** Every way to change how a candidate is scored
  gets used. The judge takes its test setup and `target.yaml` from the base commit, measures
  from a separate process, and only its own metrics (or an observer's, collected outside) can
  decide. The Darwin Gödel Machine paper reports the same thing from the other side: an agent
  removed the logging its check relied on, despite instructions not to.
- **Red team first.** `server/tests/test_redteam.py` holds 21 cheats: patching the timer,
  printing fake measurements, rigging or deleting the harness, lowering the bar, shadowing
  `unittest` or `json`, `sitecustomize`, memoising, caching on disk, sniffing the benchmark's
  environment, swapping its input, tampering with the observer, and five parameter cheats. Each
  was written to pass the old judge before the judge was fixed. The five parameter cheats all
  passed before #46.
- **Check the statistics with identical code.** Paired rounds, a median gain over the bar and a
  sign test at p ≤ 0.01: in an A/A test the judge passed identical code 0 of 12 times while a
  real speed-up passed.
- **Correctness and timing in the same runs.** Comparing each timed run's output with the
  base's means code that detects the benchmark gains nothing by doing less.
- **Ownership needs a place the agent cannot write.** The map could describe parameter owners
  but not protect them, since the agent writes the map. Enforcement went into `target.yaml`,
  read from the base commit (#46, #58).
- **Static reading has a limit.** Parameters are read from files; code that changes a setting at
  run time is left to the reviewer.

## Scope

- **Ask what the system does before adding to it.** Several rounds of work (a gateway, a
  knowledge-base design, a change log for the map, a reviewer for map changes) were cut once the
  question was asked. The scope test that survived: Morphogen needs it to judge and improve
  itself, or it is an interface where other things plug in.
- **Mapping is its own function.** It proved useful with no judge at all (the CMC map found the
  spec's gaps, unset parameters and wrong claims without one trial). It belongs to a separate
  piece.
- **Look it up first, at every level.** The ontology was designed before checking Backstage,
  C4 and CycloneDX, which already cover most of it. The rule was in CLAUDE.md and was still
  broken at the design level.
- **Most of a software map should be derived, not written.** A hand-written copy of what tools
  can extract competes with the code and drifts. Write down only what code cannot say: intent,
  roles, owners, requirements with reasons, interfaces as tests.

## Storage and documents

- **Documents and records are different things.** What people write and git versions
  (`target.yaml`, config, strategy cards) is read only through `documents.load` with a pydantic
  schema each. What tools write goes through the store. Mixing them made the loaders spaghetti.
- **Use a library, not our own store module.** SQLAlchemy Core with SQLite by default replaced
  hand-written JSONL handling. Test only the default; accept any URL.
- **Logs need their order enforced by the database.** `seq` as the primary key, retry on a
  conflict, `BEGIN IMMEDIATE` and WAL on SQLite, and triggers refusing UPDATE and DELETE. Two
  writers could otherwise fork the hash chain.
- **Keep the evidence where candidates cannot sweep it up.** The database lives in git's own
  directory, shared by every worktree.

## Evals and CI

- **Measure the plugin against no plugin.** Each eval runs with and without it. Map baseline:
  1.0 with, 0 without, over three runs. Strategy after a stall: 1.0 with, 0.5 without.
- **One run is an anecdote.** A single 0.33 run among 1.0s was a skipped tool call; three runs
  showed it.
- **Evals cost real money.** About $0.20 to $0.70 per session; start with one case.
- **The full loop (eval 03) was never verified.** The eval sandbox made `.git` read-only in a
  root container. The `eval-loop` CI job exists and needs an `ANTHROPIC_API_KEY` secret. The new
  project should close its own loop early.
- **Behind a TLS-intercepting proxy, sync dependencies before scaffolds run.** Scaffolds start
  with an empty HOME and none of the certificate settings.

## Process

- **Check the PR head before merging.** #54 merged at an older head because the PR never picked
  up later pushes.
- **Stacked PRs merge into their base branch.** Retarget each to main first (#52, #53).
- **Flaky tests often mean an undetectable case.** #49's wrong candidate (tie order) was
  indistinguishable from the right one on many seeds; the fix was a candidate that is wrong
  every time.
- **Keep portable parts free of harness-specific parts.** Skills, the server, strategies and
  samples never depended on Claude Code; that is what makes a skill-folder packaging possible
  now.
