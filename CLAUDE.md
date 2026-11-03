# Morphogen (developing the plugin)

This repository is the Morphogen Claude Code plugin. Its root is the plugin:
skills/, server/ (Python MCP server and judge), strategies/, agents/, hooks/,
samples/, evals/ (claude plugin eval suite), .claude-plugin/ (plugin and
marketplace manifests), .github/workflows/judge.yml (CI judge).
Read README.md first; it is the specification.

## Rules
- Look it up before relying on it. When a tool, library, standard or project
  is unfamiliar, or you are unsure of its current version, licence or API,
  search for its documentation and read it before designing around it,
  recommending it or saying you don't know it. Don't take a description on
  trust, the user's included, and don't answer from memory when a search is
  available. Say what you read and what you couldn't check.
- The installed plugin is the judge; this repository is the candidate. Never
  edit the installed plugin's directory, and never weaken the judge to make a
  change pass.
- Every cheat in server/tests/test_redteam.py must keep failing. A new cheat
  that passes: add it to the red team first, then fix the judge.
- After any change to the judge's statistics, run an A/A check: identical code
  must not pass (it passed 0 of 12 when last measured).
- Only judge-measured metrics (wall_seconds, cpu_seconds, max_rss_kb) or
  observed.* metrics with `collected: outside` may decide a verdict.
- Pin exact versions (server/uv.lock) and check licences before adding
  dependencies.
- Keep harness.yaml true: portable parts (skills, server, strategies,
  samples) must not depend on Claude Code-specific parts.
- Changes reach main by pull request; the `judge` workflow re-runs main's
  tests and samples against the candidate.

## Scope: what belongs in this repository
- The base passes one of two tests, or it goes elsewhere: Morphogen needs it to
  map, judge and improve itself; or it is an interface where other things plug
  in (a port, a slot, a reference field, a strategy card format, a mountable
  map, a catalog section). Domains (assistant, cognitive models, games,
  business processes, pattern libraries) live in their own repositories as
  distributions (docs/distributions.md). Private work never goes in this
  public repository, not even on a branch. No demos or domain samples here.
- Files first. Core requirements must be ones the files backend can meet: the
  lists (get, put, query, follow, dump, load) and three append-only logs
  (evidence, changes, journal). Anything more is an optional capability a
  backend reports and a slot must `require`, with a reason in `because`.
- Git versions what you would roll back (code, target.yaml and harnesses,
  config, skills, strategy cards). The logs keep the history of everything
  else.
- Harness-neutral where possible: skills in the agentskills format, the MCP
  server, strategies and samples must not depend on Claude Code.

## Checks before every commit
```
cd server && uv run --project . python -m unittest -v tests.test_morphogen tests.test_redteam tests.test_strategies
claude plugin validate . && claude plugin validate .claude-plugin/plugin.json
```

Skill changes: also run the eval suite (costs money; start with one case;
run from a clean copy, see evals/README.md):
```
claude plugin eval . --case 06-strategy-after-stall --scaffold --mocks off --judge-model sonnet --allow-tools mcp__plugin_morphogen_morphogen --no-publish
```
Cases that write or run commands (01, 03, 05) also need the operator's grant:
`--allow-tools mcp__plugin_morphogen_morphogen "Bash(git:*)" "Bash(python:*)" "Bash(python3:*)" Write Edit`,
and on Linux `bubblewrap` and `socat` for the sandbox.

## Install the judge from GitHub, not from this folder
`/plugin marketplace add OpenReplicant/morphogen` installs a copy of main into
the plugin cache. Adding this clone as a local marketplace runs the plugin
from the clone itself, so the judge would be the candidate.

## Verified
- 2026-11-02: plugin install from GitHub; the MCP server connects (15 tools
  then, 19 now, as mcp__plugin_morphogen_morphogen__*); a server-level allow
  rule grants them.
- 2026-11-02: Docker and Podman runners: all suites pass with
  MORPHOGEN_TEST_SANDBOX set; ContainerGuarantees checks no network,
  read-only tree, memory limit and nothing kept between runs. CI: run the
  judge workflow by hand.
- 2026-11-03: evals 01, 02, 04, 05 and 06 pass with the plugin (one run each;
  results in evals/README.md).
- 2026-11-03: the whole suite passes on the postgres backend
  (MORPHOGEN_TEST_BACKEND=postgres, PostgreSQL 16).

## Not yet verified
03-evolve-one-round, the full loop: in this container the eval sandbox made
.git read-only, so no candidate could be committed. Verify it on a non-root
machine or CI runner before trusting self-improvement runs.

## Releases
Bump version in .claude-plugin/plugin.json and in the marketplace entry,
tag, then /plugin update morphogen@morphogen and start a new session.

## Working notes
- Stacked pull requests merge into their base branch, not main. Retarget each
  to main before merging it (#52 and #53 landed in branches and had to be
  carried to main by a later PR).
- Postgres tests: set MORPHOGEN_TEST_POSTGRES to a scratch database URL; add
  MORPHOGEN_TEST_BACKEND=postgres to run every suite on it. In the cloud
  container, keep the cluster outside /tmp/claude-0 (its permissions get
  reset), e.g. /var/tmp/morphogen-pg, run as the postgres user.
- Evals: run from a clean copy of the tracked files with a server/uv.toml
  setting link-mode = "copy" (evals/README.md); grade with --judge-model
  sonnet; grant Bash, Write and Edit for 01, 03 and 05; on Linux install
  bubblewrap and socat. In a container running as root the eval sandbox made
  .git read-only, which blocks 03.
- Open work is tracked in issues #43 to #49 (gateway slot, environment
  targets, learned-state reset, parameters, trust tiers, eval mapping, a
  flaky test).

