# Morphogen (rebuild 7)

Read BRIEF.md first; it is the design. The previous build is on the `rebuild-6` branch, with
docs/restart/LESSONS.md.

## Layout
- `morphogen/`: the core. `structure.py` (cells, interfaces, parameters; checks, scopes,
  boundaries, intended against observed), `render.py` (Mermaid), `cli.py`.
- `tests/`: the core's tests, on their own small structures.
- `demos/`: projects Morphogen can build and drive. The core never imports from them.

## Rules
- Look it up before relying on it: read a tool's or library's current docs before designing
  around it, and say what you could not check.
- Red team first: any way to cheat the judge goes into the red-team tests before the fix, and
  every cheat there must keep failing.
- Only measurements the judge takes, or scores computed outside the candidate on cases it cannot
  read, may decide a verdict.
- Pin exact versions (uv.lock) and check licences before adding a dependency.
- Changes reach main by pull request. Before merging, check GitHub shows the head you pushed.

## Checks before every commit
```
uv run python -m unittest discover -s tests -v
```
