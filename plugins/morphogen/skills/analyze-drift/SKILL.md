---
name: analyze-drift
description: Explain differences between intended or blueprinted state and observed state on a Morphogen target. Use when drift, coverage gaps or unexpected couplings show up.
---
# Analyze drift

1. `morphogen-map.drift(target, environment)`.
2. For each item, classify:
   - **not built yet** (hypothetical, no intent);
   - **built, not observed** (intended, no observation): check instrumentation and ingest first;
   - **unexpected** (observed, not intended): new dependency, proxy, or mis-identified entity;
   - **identity mismatch**: two keys for one thing.
3. Rank explanations by evidence; cite ids.
4. Output findings (summary, severity, evidence). Recommend investigation when confidence is low; recommend a proposal only with a clear, testable fix.
