---
name: morphogen
description: Improve a system or a part of it (speed, cost, accuracy, a tunable setting) with Morphogen's judge, which the agent cannot edit. Use when the user asks to optimise, tune, speed up or improve a target, to check whether a change is really better, or to see a system's structure, its cells and the tests guarding them.
---

# Improving a system with Morphogen

Morphogen's tools (MCP server `morphogen`) give you the system's structure, a judge that scores a
change by the base commit's rules, practice probes, a parameter search, and an evidence log. The
judge is the only thing that can say a change is better; you cannot edit how it scores.

## 1. Understand what you may change

Call `status` first: the cells on the trunk, which the judge can judge (and why not), their
measurements and verdicts, and the next step. If no cell is ready, there is nothing to judge yet:
use the `map` skill to draft one with the operator first.

- `structure_check` and `structure_render`: the cells, the interfaces joining them, and which
  interfaces have tests (intent coverage). Errors (gaps, cycles) come before anything else.
- `structure_scope(cell)`: what a change inside that cell touches, and the tests it must pass.
- A target is `cell:NAME` for a cell with a `run` (or the cell's name, or its `dir`). Read the
  cell in `morphogen.yaml`. **Its `change` is all you may change**: paths and globs you may edit,
  and settings (`path#NAME in lo..hi`, `path:key in [a, b]`) you may set within their bounds, which
  in a file named only that way are the only thing you may touch. Everything else, `morphogen.yaml`
  and every test included, belongs to the judge: a candidate that changes any of it is refused
  before it runs. `keep` lists settings you may not change even in a file you may edit.

## 2. Measure first

`measure(target)` records the baseline. Look at what the primary metric is and where the time,
cost or errors go before choosing what to change.

## 3. Change, then let the judge decide

- **Settings only:** `tune(target)` searches the settings `change` gives ranges or choices, probes
  each proposal on its own branch, and sends only the best to the judge.
- **Code or structure:** make the change on a branch (one branch per approach; the `worker` agent
  builds one candidate in its own worktree), commit, use `probe(target, branch)` for feedback while
  you iterate, then `judge(target, branch)` once.

Rules that keep trials honest:

- Never edit anything outside the cell's `change` to make a change pass: the bench, the scorer,
  the tests and `morphogen.yaml` are the judge's, and a candidate that touches them is refused.
- Never try to read held-out answers or name the scorer's private directory; the candidate is
  refused.
- A probe is practice, never a verdict. Only a `pass` verdict can be proposed for merging.

## 4. Propose, do not merge

After a `pass`, ask the `reviewer` agent for an independent review of the diff, then tell the
operator: the branch, the verdict's gain and interval, the parameter values, and the reviewer's
concerns. Merging is the operator's decision.

Record what you learned that the judge did not measure with `evidence_note` (`stated` with a
source, or `inferred`). `evidence_verify` checks that the log has not been edited.
