# Related work

Survey from 2026-11. Based on search summaries only; none of these projects'
code has been read yet. Verify before citing.

The core loop isn't unique. Several projects run "change, score with a fixed
evaluator the agent can't touch, keep or discard". No project found combines
all of Morphogen's pieces.

## Highly overlapping

| Project | What it is | Overlap |
|---|---|---|
| auto-optimize (Claude Code plugin) | Builds regression and benchmark tests first, then loops: profile, plan, apply, test, measure, reflect, with a leaderboard | Closest in form: same harness, same "measure, then optimise" shape. Apparently no competing branches, outside judge or red team |
| Codeflash | Python optimiser: generates several candidates, checks behaviour is unchanged, benchmarks, opens PRs, runs as a GitHub Action | Closest for the slow-script use case, and a mature product. Python performance only |
| Karpathy's autoresearch (March 2026) | An agent edits `train.py`; `prepare.py` is the read-only evaluator; keep or `git reset`; log every run | Same core idea: a fixed evaluator, binary keep or discard, a goal file written by a human. Commentators already generalise it beyond ML (texxr) |

## Partly overlapping

- **Evolutionary search engines:** OpenEvolve, ShinkaEvolve and CodeEvolve do
  evaluator-driven program evolution with archives and islands. Closer to
  candidates for Morphogen's strategy slot than competitors.
- **pi-evolve:** mutate, evaluate, select, archive over skills and prompts.
- **agent-gate** (MCP server, MIT): a hash-chained receipt ledger, an
  independent "refute" review, and a fail-closed gate, built so agents don't
  grade their own work. Very close to Morphogen's evidence and judge design,
  without the improvement loop.
- **Claude Code loops on skills and quality:** self-optimize (evidence-backed
  self-optimisation of Claude Code usage), loop_eng (builder and checker
  cycles), torque-loop (evidence-gated single-artifact loops), learning-loop,
  MLflow's skill-refinement loop.

## Research

- **ADAS: Automated Design of Agentic Systems** (Hu, Lu, Clune;
  [arXiv:2408.08435](https://arxiv.org/abs/2408.08435), Aug 2024, revised
  Mar 2025; [project page](https://shengranhu.com/ADAS)). Meta Agent Search:
  a meta agent writes new agents as code (prompts, tool use, workflows),
  drawing on an ever-growing archive of earlier discoveries. Tested on
  coding, science and maths; the discovered agents beat hand-designed ones
  and transfer across domains and models. Overlap: an archive-driven search
  over code, the same shape as `archive-search`, and Morphogen's own
  agents and skills could be a target. Unlike Morphogen, the search objective
  is benchmark accuracy reported by the loop itself; the abstract says
  nothing about cheating or isolating the evaluator. The paper's own
  scoring method, archive rules and safety handling still need reading.
- **Darwin Gödel Machine** (same group, 2025; from memory, not yet checked):
  a coding agent that edits its own code, keeps an open-ended archive, and
  is scored on coding benchmarks. Reportedly it was caught gaming its
  evaluation, which makes it a source of cheats for
  `server/tests/test_redteam.py`.

## What looks distinctive in Morphogen

None of the above appears to combine:

- a judge hardened against cheating, with a red-team suite proving it: timing
  measured outside the process, fresh seeds, forbidden shadow modules, paired
  rounds with a sign test, and the A/A result
- trust levels, including `simulated` for models of systems you can't act on,
  plus observers that only count when collected outside the candidate
- a map and catalog of systems, slots and components, with reuse before
  generation
- swappable strategies chosen from evidence
- targets beyond code (services, people through APIs, simulators), with a CI
  judge that uses the base's harness

## Follow-ups

- Position on generality plus a trustworthy judge, not on the slow-script
  sample; Codeflash and auto-optimize already cover "make Python faster".
- Wrap OpenEvolve or ShinkaEvolve as strategy cards.
- List Codeflash in `samples/catalogs.yaml` as a candidate source for Python
  performance gaps.
- Compare agent-gate's receipt format with Morphogen's evidence records before
  they drift into incompatible formats.
- Read ADAS and the Darwin Gödel Machine papers in full: how candidates are
  scored, how the archive is kept, and any reported reward hacking to turn
  into red-team cases.
- Read autoresearch and auto-optimize closely before positioning; they're the
  nearest in spirit and in form.
