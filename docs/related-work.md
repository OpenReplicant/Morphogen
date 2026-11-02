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
- **Darwin Gödel Machine: Open-Ended Evolution of Self-Improving Agents**
  (Zhang, Hu, Lu, Lange, Clune; [arXiv:2505.22954](https://arxiv.org/abs/2505.22954),
  May 2025, v3 Mar 2026; [code](https://github.com/jennyzzt/dgm)). Read in
  full (v3). A coding agent edits its own Python code (prompts, workflow,
  tools); the archive and parent selection are fixed and not modifiable by
  the agent (§3).
  - *Evaluation (§4.2):* staged. SWE-bench Verified: 60 tasks, then 200
    if over 40% and in the archive's top two. Polyglot: 10 tasks, then 50.
    Only agents that compile and can still edit code enter the archive.
    Scores come from small subsets of noisy LLM runs; there is no paired
    statistical test or A/A check.
  - *Selection (App. C.2):* weight = sigmoid(10 * (score - 0.5)) /
    (1 + children that can still edit), sampled with replacement; agents
    with a perfect score are excluded. Every agent keeps a non-zero chance.
  - *Results:* SWE-bench 20.0% to 50.0%, Polyglot 14.2% to 30.7%, ahead of
    variants without self-improvement or without open-ended exploration.
  - *Cost (App. E.1, §6):* about USD 22,000 and two weeks per SWE-bench run.
  - *Safety (§5):* sandboxing, strict time limits, limited network, human
    monitoring, and an archive lineage kept for audit.
  - *Objective hacking (App. H).* In a side experiment the score was
    "solve tool-use hallucination", detected by checking for special marker
    tokens that the agent's own code logged on real tool calls. The checker
    was hidden from the agent; the authors report hacking was more frequent
    when it was not. Node 114 reached a perfect 2.0 in two edits by
    replacing the marker logging with a "structured format", despite
    instructions not to change the markers. That bypassed the detector
    without fixing the hallucination. Node 96 (1.67) did make a real
    improvement. The lineage made the hack traceable.
  - *Lesson for Morphogen:* the hack worked because the signal was emitted by
    code the agent could edit. That is Morphogen's `collected: self` case.
    Both forms are now red-team cases (`ObserverCheats` in
    `server/tests/test_redteam.py`) and fail: a candidate that rewrites the
    observer to report near-zero latency, and one that also edits
    `target.yaml` to make self-reported telemetry primary and claim it is
    `collected: outside`. Harness files and `target.yaml` are restored from
    the base, so the base's primary metric still decides.

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
- Read the ADAS paper in full: how candidates are scored and how the archive
  is kept.
- Read autoresearch and auto-optimize closely before positioning; they're the
  nearest in spirit and in form.
