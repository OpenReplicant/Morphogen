---
name: propose-change
description: Write and send a Morphogen proposal (hypothesis, predictions, risk, rollback) through morphogen-map.propose. Use whenever a change to a target is wanted.
---
# Propose a change

1. `morphogen-map.status(target)`. Kill switch on → stop and report.
2. `morphogen-map.blast_radius(affected slots)`. More than the budget in `intent/policies/autonomy.yaml` → split the change.
3. Choose the risk class: low (reversible, small radius), medium, high, irreversible (data loss, external commitments). When unsure, go one higher.
4. Write the change as declarative files under `base/`, `environments/<env>/` or `experiments/<id>/`. Default environment: sandbox.
5. Hypothesis: one sentence on what will change and why.
6. Predictions: at least one, each with observation, comparison, value, window, and min_samples; add a control when one exists.
7. Evidence: the claim or event ids that motivated it.
8. Rollback: how to undo it (usually reverting the commit).
9. Call `morphogen-map.propose`. A 400 lists schema errors; fix and resend. Report the proposal id.

Never edit `intent/` yourself; the promoter commits approved proposals.
