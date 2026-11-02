---
name: evolve
description: Close one gap in a target through Morphogen's loop - locate the bottleneck, source candidates (reuse before writing new code), build them on branches, have the judge score each, and propose the winner to the operator. Use when the user asks to improve, speed up or optimise a target, or to work through Morphogen's gaps.
---

# Evolve

One gap per run. The judge decides what is better; you decide what to try.

## The loop

**Know**
1. If the target is not mapped or has no baseline, run `/morphogen:map` first.
2. Read `intent.md` and `morphogen.yaml`: the purpose, constraints, autonomy
   and budgets.
3. Read recent evidence (`evidence_query`), including failed verdicts, so
   you do not repeat a losing idea.

**Change**
4. **Locate.** Name the one slot that limits the target, with evidence
   (a profile, a measurement). If you cannot, have the `explorer` subagent
   profile it.
5. **Source, in this order:** reuse (`catalog_search`; the standard library;
   existing components), configure (settings of what is there), compose
   (combine existing parts), generate (write new code). Use a later rung
   only when the earlier ones do not fit, and say why.
6. **Trial.** Pick two or three genuinely different approaches. For each,
   launch a `worker` subagent with the approach and a branch name
   (`morphogen/<target>-<approach>`), in parallel.

**Keep**
7. **Judge** each candidate commit with the `judge` tool (base: the trunk).
   Report every verdict, including failures and their reasons.
8. **Review** the best passing candidate with the `reviewer` subagent, giving
   it only the diff and `target.yaml`.
9. **Swap.** At autonomy 1 or 2, propose the merge to the operator with the
   verdict and the review, and merge only on their approval. Never merge a
   candidate that did not pass the judge.
10. **Record.** Call `journal_append`: the gap, the options tried, the
    choice and why, the rung, the verdicts, the commit. Update the lists if a
    slot is now filled by a different component.

## Rules

- Never edit a target's harness files or `target.yaml`, the evidence log, or
  the judge. Never tune code to the benchmark's input: the judge's inputs are
  hidden and change per project.
- A failed verdict is a result. Record it and use it; do not retry the same
  idea with cosmetic changes.
- Stop when the budget in `morphogen.yaml` is spent, or after three rounds
  without a pass, and report what you learned.
