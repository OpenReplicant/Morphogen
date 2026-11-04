# Restart brief: Morphogen as the local morphological drive

Written 2026-11-04, when this repository was frozen. It is the starting point for a new
project, not a plan for this one. Read [LESSONS.md](LESSONS.md) alongside it.

## What it is

In development, cells do not consult a blueprint. Each reads a morphogen's concentration where
it sits and responds; the shape emerges from many local responses. Morphogen is that drive for
software and agent systems: at each point it is given, it measures, searches for a better
filling, and proposes the change with its evidence.

It is one subsystem of a larger cognitive framework, operable alone:

| Piece | Job | Relation to Morphogen |
|---|---|---|
| **Mapper** | builds representations: intent and observed maps, catalogs, taxonomies | produces the points Morphogen works on; reads Morphogen's evidence back |
| **Builder** | builds from a spec, fixes, upgrades, instruments (ordinary Claude Code) | closes what the map intends but the system lacks; assembles candidates |
| **Morphogen** | changes a system locally, point by point, against a judge it cannot edit | this project |
| **Deploy** | the target's own release process | Morphogen stops at a proposed change; what deploy observes comes back as evidence |

## What it is not

- **Not a search algorithm.** GEPA, OpenEvolve, AFlow, Optuna and the like search better than
  anything we would write. Morphogen runs them at points.
- **Not the mapper.** It needs a list of points, not a model of the system. Maps, catalogs and
  the intent-versus-observed comparison belong to the mapper (or Backstage plus an indexer).
- **Not the builder, and not deploy.**

## What Morphogen adds around any optimizer

| # | Addition | Carried over from this repo |
|---|---|---|
| 1 | **Points**: the unit of work, with location, modality, interface test, parameters with owners and ranges, and neighbours | `target.yaml` and declared parameters (#58); neighbours and modality are new |
| 2 | **The protected judge**: test setup from the base commit, owners enforced, paired statistics with an A/A check, equivalence, only measured metrics decide, a red team that must keep failing | `server/morphogen/judge.py`, `runner.py`, `tests/test_redteam.py` |
| 3 | **Held-out cases**: the judge scores the optimizer's best on cases the search never saw | new |
| 4 | **Neighbour checks**: a structural change (split, merge, swap, rewire) passes only if the neighbours' interface tests pass too | new |
| 5 | **The gradient**: which point to work on, and with how much budget, from measured gaps across points | bottleneck search exists within one target only |
| 6 | **Optimizer selection**: chosen mostly by modality, updated by evidence of what worked | strategy cards and stall handling (eval 06); the optimizer catalogue is new |
| 7 | **Evidence**: claims from every optimizer and run, with trust classes, append-only and hash-chained | `store.py` evidence log, `ports.TRUST` |
| 8 | **The promotion boundary**: Morphogen proposes, the operator merges | convention plus the reviewer agent |

## Two tiers of evaluation

Optimizers call their evaluator hundreds of times; the judge is too slow and costly for that.

- **Inner evaluator**, for the search. Cheap, not statistical, and outside the optimizer's
  reach: it runs from a copy the candidate cannot write, in a separate process or container.
  Handed to the optimizer as its evaluator function (GEPA's `optimize_anything` evaluator,
  OpenEvolve's evaluation file, an Optuna objective).
- **The judge**, for promotion. Runs once on the optimizer's best, with full statistics, on
  held-out cases the search never saw.

The held-out split matters even without cheating: searching hard against one evaluator
overfits to it.

## The points format (draft)

```yaml
points:
  retrieval-prompt:
    at: agent/prompts/retrieve.md        # a file, file#symbol, or a marked block
    modality: text                       # text | code | numeric | workflow | ...
    interface:                           # what any replacement must pass
      check: python -m pytest -q tests/test_retrieve.py
    parameters:                          # the #58 format, unchanged
      top_k: {file: agent/config.yaml, key: retrieve.top_k, owner: agent, range: [1, 50]}
      model: {file: agent/config.yaml, key: llm.model, owner: operator}
    neighbours: [answer-prompt, memory-store]   # their interface checks run on structural changes
    measure: targets/qa                  # a directory with target.yaml: harness, metrics, cases
    cases: {search: cases/search, holdout: cases/holdout}   # holdout is read by the judge only
    alternatives: catalog/retrieval      # optional: where candidate fillings come from
```

A mapper writes this file, or a person does by hand. Morphogen reads it and nothing else about
the system.

## Optimizer catalogue (first entries)

| Modality | Optimizer | Licence | Notes from the source (read 2026-11-04) |
|---|---|---|---|
| text, DSPy programs | GEPA 0.1.4 | MIT | candidate is a dict of named texts; one component per round or all at once; merge of Pareto candidates; DSPy adapter changes signatures, modules and control flow; evaluator isolation is the user's (`code_execution` has an in-process and a subprocess mode) |
| marked code blocks | OpenEvolve 0.4.1 | Apache-2.0 | evaluator file is imported into OpenEvolve's own process; timeouts and retries, no sandbox |
| workflow graphs | AFlow | not checked | Monte Carlo tree search over workflows as code; evaluator details not read |
| numeric settings | Optuna | not checked | the obvious first choice; not yet read |
| anything, by an agent | Claude Code workers with strategy cards | ours | what this repo does today |

## First milestone

One prompt point, GEPA as its optimizer, end to end:

1. GEPA improves the inner score.
2. The judge on held-out cases accepts a real improvement and refuses an overfit one.
3. Red team, before anything else is built: a candidate that reads or edits the inner
   evaluator, or the held-out cases, is refused.
4. The verdict records GEPA as the optimizer and the parameter values, as evidence.

Then, in order: a numeric point with Optuna; a structural change gated by a neighbour's
interface test; the gradient across two or more points.

## Packaging

A skill folder per piece is the portable core (Agent Skills format: `SKILL.md`, scripts, data).
Claude Code extras come from an optional `.claude-plugin/plugin.json` in the same folder, which
Claude Code loads as `<name>@skills-dir` with its own agents, hooks and MCP servers (an
administrator can block this). Subagents shipped inside a plugin ignore `mcpServers` and
`hooks`; a fully configured subagent works only as a project or user agent. Checked against
code.claude.com/docs (skills, sub-agents) on 2026-11-04.

## Carry over, drop

| Carry over | Drop (or hand to the mapper) |
|---|---|
| judge: statistics, overlay of the test setup, parameter reading, probes | lists, maps, mounting, catalogs, the self-map |
| runners (Docker, Podman, none) | map, onboard and playbook skills; the explorer agent |
| the red team, every cheat | knowledge-system slots and role slots |
| the evidence log and trust classes | the admin UI |
| `documents.load` with a schema per document | most of the 19 MCP tools: keep judge, measure, evidence |
| the worker and reviewer agents | |
| evals with and without the plugin; the eval-loop CI job | |

## Open questions

- How to run neighbours' interface tests without the judge's cost multiplying per point.
- Where held-out cases live so no candidate can read them: outside the container, or only in
  the judge's process.
- Learned-state reset between trials for stateful targets such as an agent's memory (#45).
- Token cost measured from outside, through a model gateway (#43).
- AFlow's evaluator; Optuna; the scip-python and scip-typescript licences (not stated on the
  SCIP page).
- Whether optimizer selection by modality needs more than a lookup table plus evidence.

## Research this rests on

- Mapping: Backstage system model, well-known relations and descriptor format (API kind holds
  `spec.definition`); C4 and the Structurizr DSL; CycloneDX 1.6 (component `evidence` with
  `confidence` and `methods`, `dependencies` with `provides`, signed `annotations`); SCIP
  (Apache-2.0); codebase-memory-mcp (MIT, v0.12.1; `CONFIGURES` links environment variables
  and config keys to code by name, not values); software reflexion models (Murphy, Notkin,
  Sullivan, FSE 1995: convergences, divergences, absences between an intent model and the
  source, through a declarative mapping).
- Optimizers: GEPA (arXiv 2507.19457, github.com/gepa-ai/gepa), OpenEvolve
  (github.com/codelion/openevolve), AFlow (arXiv 2410.10762), Darwin Gödel Machine (arXiv
  2505.22954; its appendix reports objective hacking: an agent removed the logging of the
  tokens its hallucination check relied on, despite instructions not to).
- Parameter ownership: no standard found. flagd's flag format has free-form `metadata` only;
  Atlas has ownership rules for database schema objects.
