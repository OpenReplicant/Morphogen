# Morphogen (developing the plugin)

This repository is the Morphogen Claude Code plugin. Its root is the plugin:
skills/, server/ (Python MCP server and judge), strategies/, agents/, hooks/,
samples/, evals/ (claude plugin eval suite), .claude-plugin/ (plugin and
marketplace manifests), .github/workflows/judge.yml (CI judge).
Read README.md first; it is the specification.

## Rules
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

## Install the judge from GitHub, not from this folder
`/plugin marketplace add OpenReplicant/morphogen` installs a copy of main into
the plugin cache. Adding this clone as a local marketplace runs the plugin
from the clone itself, so the judge would be the candidate.

## Verified (2026-11-02)
- Plugin install from GitHub; the MCP server connects and exposes 15 tools as
  mcp__plugin_morphogen_morphogen__*; a server-level allow rule grants them.
- Docker and Podman runners: all suites pass with MORPHOGEN_TEST_SANDBOX set,
  and ContainerGuarantees checks no network, read-only tree, memory limit and
  nothing kept between runs. CI: run the judge workflow by hand.

## Not yet verified
The eval suite beyond one run of 02-map-baseline (passed). Verify the rest,
especially 03-evolve-one-round, before trusting self-improvement runs.

## Releases
Bump version in .claude-plugin/plugin.json and in the marketplace entry,
tag, then /plugin update morphogen@morphogen and start a new session.
