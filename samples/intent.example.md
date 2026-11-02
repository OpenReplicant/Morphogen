# Intent

The operator writes this file; Morphogen reads it and never edits it.

## Purpose

Make `targets/slow-script` faster without changing its results.

## Goals and constraints (SLOs)

- Results identical to the trunk on hidden inputs (the judge checks this).
- `seconds` at least 10% lower than the trunk for every adopted change.
- Prefer the simplest change that clears the bar.

## Hard limits

- Never edit a target's harness files (`harness:` in its `target.yaml`) or the judge.
- Never merge to the trunk without the operator's approval (autonomy 2).
- Ask before installing packages or using the network.
- Never rewrite the journal or the evidence log.
