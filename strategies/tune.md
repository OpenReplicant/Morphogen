---
name: tune
description: Search the settings of a component without changing its structure - constants, sizes, thresholds, model choice, prompt temperature - by random search first, then narrowing around the best. After random and Bayesian search.
when: The design is right but its settings may not be; the operator has named which settings are the agent's to change.
weak_when: The gap needs a different design, not different numbers; or no settings are named as the agent's to change.
---

# tune

**Parent:** the tip of the trunk.

**Settings:** only the agent-owned parameters in the target's `target.yaml`,
within their `range` or `choices`. The judge refuses a candidate that changes
any other parameter or leaves a range, so ask the operator to declare a
setting there before tuning it. A change inside a component's interface is a
setting; a change to its structure or contract is a new component and belongs
to another strategy.

**Candidates:**
1. Take each setting's range from `target.yaml`. Draw five to eight random
   combinations (a baseline that any smarter search must beat).
2. `probe` each with few rounds. Narrow the ranges around the best two or
   three and draw again, halving the count each time.
3. Commit the best one or two combinations as candidates, labelled with the
   values (`family: tune`, `approach: <setting=value, ...>`).

**Judging:** `judge` each against the trunk. Probes only rank; the verdict
decides.

**After:** propose the best passing candidate with its values; the verdict
records them (`parameters` in the evidence). Record the
probed combinations and their metrics with `evidence_note` (trust
`inferred`), so the next tune starts where this one ended.

**Stop:** when a narrowing round improves on the best probe by less than the
target's bar.
