# Morphogen (rebuild 7)

Read BRIEF.md first; it is the design. The previous build is on the `rebuild-6` branch, with
docs/restart/LESSONS.md.

## Layout
- `morphogen/`: the core. `structure.py` (cells, interfaces, parameters; checks, scopes,
  boundaries, intended against observed), `render.py` (Mermaid), `judge.py` and `runner.py` (the
  judge), `serve.py` (the env values, services and model gateway a run is given; the meter), `errors.py`, `evidence.py`, `optimize.py` (the optimizer catalog, the selector and `tune`), `observers.py` (`command`,
  `otel`), `project.py` (the cell format: morphogen.yaml's cells and interfaces, default deny),
  `backstage.py` (catalog-info.yaml files as a source of cells),
  `status.py` (where a project stands and the next step),
  `documents.py` (morphogen.yaml's settings, and the target spec a cell compiles to), `cli.py`, `mcp_server.py`, `ui.py` and `ui.html` (the read-only web UI).
- `.claude-plugin/`, `skills/`, `agents/`: the Claude Code plugin around the MCP server. Skills:
  `morphogen` (improve a cell) and `map` (draft morphogen.yaml's cells).
- `tests/`: the core's tests and red team; fixture projects in `tests/fixture*.py`, the timed
  sample's files in `tests/fixtures`.
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
uv run --extra optuna --extra gepa python -m unittest discover -s tests -t . -v
MORPHOGEN_TEST_SANDBOX=podman uv run --extra optuna --extra gepa python -m unittest discover -s tests -t .   # judge or runner changes
claude plugin validate . && claude plugin validate .claude-plugin/plugin.json
```

## Install the judge from GitHub, not from this folder
`/plugin marketplace add OpenReplicant/Morphogen`, then `/plugin install morphogen@morphogen`,
installs a copy of main. A
local clone added as a marketplace runs the plugin from the clone, so the judge would be the
candidate. Never edit the installed plugin's directory.

## State (2026-11-05)
- On main through phase 5 of PLAN.md (#65-#70). Phase 6 has started: `inputs` outside the
  repository, and the entity-resolution demo judged in Podman (see its README).
- Tests pass (1 container-only case skipped without Podman); run the whole suite in Podman after
  judge or runner changes. A/A: 0 of 12 in the cell format.
- CI: `judge` runs the candidate's tests (required on main); `base-tests` runs main's red team
  against the candidate (every cheat main refuses must still be refused). It is not required yet;
  it can be now that it no longer fails on intended changes.
- Podman, Docker and bubblewrap are installed in the cloud container; only Podman's service runs.
- Model calls: run them through this session's Claude Code (the user's subscription), never an API
  key. Headless runs and subagents use sonnet: `claude -p --model sonnet`, and `model: sonnet` for
  subagents. GEPA's reflection does this through `optimize.ClaudeCLI` (no tools, an empty directory).
  `MORPHOGEN_LIVE_MODEL=1` runs the one live GEPA test.

## Next
[PLAN.md](PLAN.md) brings everything into the small-core paradigm (phases 0-6), and phase 7 makes the
judge callable by any system and tests the value claims before it is published; the items below fold
into it.

1. Design simplifications left: probe as a mode of the judge. Done: one structure document
   (morphogen.yaml, phases 1-2), one kind of "still works" test (`tests`, `same_as_base`).
2. Optimizers that escape local optima: done (hill-climb restarts, `anneal`, the selector's
   stagnation signal). Later: a stepping-stone archive and multi-step candidates.
3. The entity-resolution demo as the first real run: move its F1 into a scorer outside the
   candidate, contract tests for its three untested interfaces, then tune the matcher.
4. An agent target: Claude Code on a small task set, cells for its skills and prompts, measured by
   the `otel` observer.
   First candidate: the mapper skill itself (`skills/map/SKILL.md`), scored against gold maps of
   small systems held outside the repository, with GEPA as the optimizer (BRIEF, "The mapper as a
   target").
5. Later: model-based selector policy, choosing scope, learned-state
   reset (#45), model gateway (#43), the observed structure from traces, a bubblewrap runner.

## Consolidated (2026-11-05)
Cell parameters are enforced and searched; one measuring loop (`judge._rounds`) for
judge, probe, measure and the system guard; target resolution in `targets.py`; the brief trimmed
to the design (status lives in README); fixtures split by project; rebuild 6 wording removed.
Left for the operator: stale rebuild 6 branches on GitHub, and issues #43-#49, which describe
rebuild 6 code.
