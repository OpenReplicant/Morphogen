# Morphogen (rebuild 7)

Read BRIEF.md first; it is the design. The previous build is on the `rebuild-6` branch, with
docs/restart/LESSONS.md.

## Layout
- `morphogen/`: the core. `structure.py` (cells, interfaces, parameters; checks, scopes,
  boundaries, intended against observed), `render.py` (Mermaid), `judge.py` and `runner.py` (the
  judge), `evidence.py`, `optimize.py` (the optimizer catalog, the selector and `tune`), `observers.py` (`command`,
  `otel`), `documents.py` (morphogen.yaml,
  target.yaml), `cli.py`, `mcp_server.py`, `ui.py` and `ui.html` (the read-only web UI).
- `.claude-plugin/`, `skills/`, `agents/`: the Claude Code plugin around the MCP server.
- `tests/`: the core's tests and red team, with sample targets in `tests/fixtures`.
- `demos/`: projects Morphogen can build and drive. The core never imports from them.

## Rules
- Look it up before relying on it: read a tool's or library's current docs before designing
  around it, and say what you could not check.
- Red team first: any way to cheat the judge goes into the red-team tests before the fix, and
  every cheat there must keep failing.
- Only measurements the judge takes, or scores computed outside the candidate on cases it cannot
  read, may decide a verdict.
- After any change to the judge's statistics, run an A/A check: identical code must not pass (0 of
  12 on 2026-11-05).
- Pin exact versions (uv.lock) and check licences before adding a dependency.
- Changes reach main by pull request. Before merging, check GitHub shows the head you pushed.

## Checks before every commit
```
uv run --extra optuna python -m unittest discover -s tests -t . -v
MORPHOGEN_TEST_SANDBOX=podman uv run --extra optuna python -m unittest discover -s tests -t .   # judge or runner changes
claude plugin validate . && claude plugin validate .claude-plugin/plugin.json
```

## Install the judge from GitHub, not from this folder
`/plugin install morphogen --marketplace OpenReplicant/Morphogen` installs a copy of main. A
local clone added as a marketplace runs the plugin from the clone, so the judge would be the
candidate. Never edit the installed plugin's directory.

## State (2026-11-05)
- On main: the base (#61), MCP server, plugin and web UI (#62). Open: #63, the optimizer catalog
  and selector, the system guard, the README comparison, and the observer slot (`otel`).
- 108 tests pass (1 container-only case skipped); the whole suite passes in Podman (98 tests at
  the system guard; rerun after observers). A/A: 0 of 12.
- CI is advisory: `judge` runs the candidate's tests (required on main); `base-tests` runs main's
  tests against the candidate and is not required. Make it required again when rebuild 7 settles.
- Podman, Docker and bubblewrap are installed in the cloud container; only Podman's service runs.

## Next
1. Consolidate (below), then open a PR.
2. Optimizers that escape local optima: random restarts, simulated annealing, a stagnation signal
   for the selector; later a stepping-stone archive and multi-step candidates.
3. The entity-resolution demo as the first real run: move its F1 into a scorer outside the
   candidate, contract tests for its three untested interfaces, then tune the matcher.
4. An agent target: Claude Code on a small task set, cells for its skills and prompts, measured by
   the `otel` observer (needs a model API key; costs money).
5. Later: GEPA adapter (text cells), model-based selector policy, choosing scope, learned-state
   reset (#45), model gateway (#43), the observed structure from traces, a bubblewrap runner.

## To consolidate
- Parameters are declared in target.yaml (enforced, searched) and in cells.yaml (shown, unused).
  When a cell is judged or tuned, its cells.yaml parameters should be enforced and searched too.
- judge.py repeats one measuring loop in judge, probe, measure and the system guard; make it one.
- `cell:NAME` is parsed in cli.py, mcp_server.py and optimize callers; mcp_server imports cli's
  `_target`. Move target resolution next to the judge.
- BRIEF.md has drafts the code has overtaken (the cells format, "points", the first milestone):
  trim it to the design, and keep status in README only (README, BRIEF and CLAUDE.md all list it).
- Wording left from rebuild 6 (probe docstrings mention strategies and an archive).
- tests/fixture.py holds six sample projects; split it by project.
- Repository: stale rebuild 6 branches on GitHub and issues #43-#49 that describe rebuild 6 code.
