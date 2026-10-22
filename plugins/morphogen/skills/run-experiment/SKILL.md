---
name: run-experiment
description: Design or evaluate a Morphogen experiment: control, statistical predictions, sandbox environment, verdict. Use when testing a hypothesis or checking a committed proposal's outcome.
---
# Run an experiment

Design:
1. Name the control (current provider or a baseline).
2. Predictions with effect size, window and minimum samples.
3. Sandbox environment via `experiments/<id>/`; input replayed from the archive or mirrored, with side effects stubbed.

Evaluate (after the window):
1. Gather observations for each prediction and the control.
2. Verdict per prediction: supported, refuted, inconclusive (too few samples counts as inconclusive).
3. Report as a finding; the verdict becomes evidence that updates belief. Promotion goes sandbox → canary → full through new proposals.
