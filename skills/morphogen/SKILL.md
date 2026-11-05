---
name: morphogen
description: Improve a system or a part of it (speed, cost, accuracy, a tunable setting) with Morphogen's judge, which the agent cannot edit. Use when the user asks to optimise, tune, speed up or improve a target, to check whether a change is really better, or to see a system's structure, its cells and the tests guarding them.
---

# Improving a system with Morphogen

Morphogen's tools (MCP server `morphogen`) give you the system's structure, a judge that scores a
change by the base commit's rules, practice probes, a parameter search, and an evidence log. The
judge is the only thing that can say a change is better; you cannot edit how it scores.

## 1. Understand what you may change

- `structure_check` and `structure_render`: the cells, the interfaces joining them, and which
  interfaces have tests (intent coverage). Errors (gaps, cycles) come before anything else.
- `structure_scope(cell)`: what a change inside that cell touches, and the tests it must pass.
- A target is a directory with `target.yaml`, or `cell:NAME` for a cell with a `measure`. Either
  way, a target that is a cell's `measure` is judged as that cell (interface tests, the system
  guard). Read its
  `target.yaml`: the harness files and `target.yaml` itself belong to the judge, and its
  `parameters` say which settings you may change (owner `agent`, within `range` or `choices`).
  Settings owned by `operator` or `judge` are not yours.

## 2. Measure first

`measure(target)` records the baseline. Look at what the primary metric is and where the time,
cost or errors go before choosing what to change.

## 3. Change, then let the judge decide

- **Settings only:** `tune(target)` searches the agent-owned parameters (grid or random), probes
  each proposal on its own branch, and sends only the best to the judge.
- **Code or structure:** make the change on a branch (one branch per approach; the `worker` agent
  builds one candidate in its own worktree), commit, use `probe(target, branch)` for feedback while
  you iterate, then `judge(target, branch)` once.

Rules that keep trials honest:

- Never edit a target's harness files or `target.yaml` to make a change pass; the judge uses the
  base's copies and records that you tried.
- Never try to read held-out answers or name the scorer's private directory; the candidate is
  refused.
- A probe is practice, never a verdict. Only a `pass` verdict can be proposed for merging.

## 4. Propose, do not merge

After a `pass`, ask the `reviewer` agent for an independent review of the diff, then tell the
operator: the branch, the verdict's gain and interval, the parameter values, and the reviewer's
concerns. Merging is the operator's decision.

Record what you learned that the judge did not measure with `evidence_note` (`stated` with a
source, or `inferred`). `evidence_verify` checks that the log has not been edited.
