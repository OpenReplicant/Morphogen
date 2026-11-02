---
name: playbook
description: Morphogen's working methods - the systems engineer, data scientist and DevOps crafts, program shapes and when each wins, and the rules that keep trials honest. Use when planning an improvement, choosing between approaches, or when a trial result is surprising.
---

# Playbook

Advice, revised on evidence. When a verdict contradicts something here, say
so and record it with `evidence_note`.

## Data scientist: evidence

- Frame first: what is the target metric, and what must not get worse?
- Baseline before changing anything. Look at the data (profile, inputs)
  before modelling.
- Try several different families of solution, not variations of one.
- Leakage is cheating: anything that lets a candidate see the judge's inputs
  or harness invalidates the trial.
- Many trials against one judge can win by luck. Prefer clear gains to
  marginal ones, and count how many trials a result took.
- Ship the simplest candidate that clears the bar.

## Systems engineer: structure

- Decompose by interfaces. A slot is worth naming only if it could be filled
  differently.
- Contracts before contents: what must stay true (outputs, errors, ordering)?
- Check what a change touches before making it.
- Reuse before building: standard library, then catalogs, then new code.

## DevOps / SRE: operation

- Run untrusted trials in the sandbox when it is available.
- Small, reversible changes on branches; the trunk changes only by an
  approved, judged merge.
- Respect budgets. When they are spent, stop and report.
- Record everything, failures included.

## Program shapes and when they tend to win

| Shape | Wins when |
|---|---|
| hash map, set, `Counter` | counting, membership, de-duplication |
| sort, heap, bisect | ordering, top-k, range search |
| cache or memo | the same work repeats |
| rules or a table | few conditions with crisp boundaries |
| search or planning | combinatorial choices with known rules |
| graph | relations and paths |
| vector index | fuzzy similarity |
| small model or classifier | many noisy features |
| cheaper LLM with a tight prompt | language-shaped tasks |
| cascade | a cheap step handles most cases and passes the rest on |

## Combining

Cascade (cheap first), distillation (expensive outputs become training data
for a cheap part), residual (rules plus a learned correction), verification
(one part proposes, another checks), ensemble with reconciliation.
