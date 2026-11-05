# Morphogen (rebuild 7)

Read BRIEF.md first; it is the design. The previous build is on the `rebuild-6` branch, with
docs/restart/LESSONS.md.

## Layout
- `morphogen/`: the core. `structure.py` (cells, interfaces, parameters; checks, scopes,
  boundaries, intended against observed), `render.py` (Mermaid), `judge.py` and `runner.py` (the
  judge), `evidence.py`, `optimize.py` (optimizers and `tune`), `documents.py` (morphogen.yaml,
  target.yaml), `cli.py`, `mcp_server.py`.
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
uv run python -m unittest discover -s tests -t . -v
claude plugin validate . && claude plugin validate .claude-plugin/plugin.json
```

## Install the judge from GitHub, not from this folder
`/plugin install morphogen --marketplace OpenReplicant/Morphogen` installs a copy of main. A
local clone added as a marketplace runs the plugin from the clone, so the judge would be the
candidate. Never edit the installed plugin's directory.
