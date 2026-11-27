---
title: Inkling 2 Mini was tested against the 27B+ finding, not only LFM3
description: The decision-gates paper found that 27B and 31B models read by option likelihood match Jev. E-04a tried that on both of our models.
kind: note
date: 2026-11-27
refs:
  - claim:gates-likelihood-readout-27-31b-matches-jev
  - resource:inkling-2-mini-q4-k
  - resource:lfm3-1.7b-q6-k
  - trial:E-04a
---

The claim that untuned Gemma-4-31B and Qwen3.6-27B, read by the likelihood of each option key, match Jev has two
assessments here, and they disagree, so its badge says **Mixed**:

- on **LFM3 1.7B** it did not transfer: pooled accuracy 0.528 against Jev's 0.842 on 3,412 JevBench cases;
- on **Inkling 2 Mini** (about 26B in all, so near the paper's sizes) it held in the sense E-04a registered: 0.810
  against Jev's 0.843 on the same 779 cases, 3.3 points below.

Both outcomes come from [E-04a](../trials/e-04a.html). The [Inkling 2 Mini page](../resources/inkling-2-mini-q4-k.html)
lists every claim tested with it, and the [claim's page](../claims/gates-likelihood-readout-27-31b-matches-jev.html)
starts with the table of both results.
