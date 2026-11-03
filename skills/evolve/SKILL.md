---
name: evolve
description: Close one gap in a target through Morphogen's loop - locate the bottleneck, follow the selected improvement strategy to build candidates on branches, have the judge score each, and propose the winner to the operator. Use when the user asks to improve, speed up or optimise a target, or to work through Morphogen's gaps.
allowed-tools: Read, Glob, Grep, Write, Edit, Agent, Bash(git:*), Bash(python:*), Bash(python3:*), mcp__plugin_morphogen_morphogen
---

# Evolve

One gap per run. The judge decides what is better; the **strategy** decides
what to try; the operator decides what is merged.

## The fixed loop

These steps never change, whatever the strategy.

**Know**
1. If the target is not mapped or has no baseline, run `/morphogen:map` first.
2. Read `intent.md` and `morphogen.yaml`: purpose, constraints, autonomy,
   budgets.
3. Call `strategy(target)`. It returns the strategy to follow, the reason,
   its card, the payoff of each strategy so far, and recent variants. Tell the
   operator the strategy and the reason in one line. If it says `stop`,
   report and end.

**Change**
4. **Locate** the one slot that limits the target, with evidence (a profile, a
   measurement). If you cannot, have the `explorer` subagent profile it. A
   capability gap reported by `maps` or `doctor` (a slot whose filler lacks a
   capability it requires) is a located gap too: source a filler that covers
   it with `catalog_search(slot=...)`.
5. **Source** in this order: reuse (`catalog_search`, the standard library,
   existing components), configure, compose, generate. Say why you used a
   later rung.
6. **Follow the card** for the parent and the candidates. Launch one `worker`
   subagent per candidate, in parallel, each with the approach, the parent
   commit and a branch name (`morphogen/<target>-<strategy>-<family>`).

**Keep**
7. **Judge** each candidate with `judge`, passing
   `labels: {strategy, family, approach, parent}`. Use the base the card names;
   the default is the trunk. Report every verdict, failures included.
8. **Review** the best candidate that passes **against the trunk** with the
   `reviewer` subagent, giving it only the diff and `target.yaml`.
9. **Swap.** At autonomy 1 or 2, propose the merge to the operator with the
   verdict and the review; merge only on their approval. Never merge a
   candidate that has not passed against the trunk.
10. **Record** with `journal_append`: the gap, the strategy and why, options
    tried, the choice, the rung, the verdicts, the commit. Update the lists if
    a slot is now filled by a different component, with `lists_put` and a
    `because` citing the verdict (`evidence:<seq>`) where a requirement
    changed.

## Rules

- A strategy only proposes. It never changes the judge, the budgets or the
  adoption rule.
- Never edit a target's harness files or `target.yaml`, the evidence log, or
  the judge. Never tune code to the benchmark's input.
- A failed verdict is a result: record it, use it, do not repeat it with
  cosmetic changes.
- A target with `interface: simulated` is a model of something you cannot act
  on directly. Its verdicts have trust `simulated`: report them as results
  about the model, and never apply the change to the real system without a
  direct trial or the operator's explicit approval.
- Stop when the budget in `morphogen.yaml` is spent, and report.

## Strategies

`strategies_list` shows the catalog. A project can add cards in its own
`strategies/` directory (Markdown with `name`, `description`, `when` front
matter, and Parent, Candidates, After, Stop sections). `strategy: auto` in
`morphogen.yaml` lets Morphogen choose from evidence; a strategy name forces
one.
