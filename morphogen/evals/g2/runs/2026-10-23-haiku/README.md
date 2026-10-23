# G2 gate run, 2026-10-23: a candidate built by Haiku

`KK_G2_BUILDER=harness`, with `claude -p` on Haiku as the builder (prompt: `x04e3cbc21296/prompt.md`,
its output: `harness.log`). G2 passed.

- Incumbent `urn:kk:provider:anomaly`: observed at 0.144 s a pass, over the person's limit of 0.12 s (this
  run used the fixed limit; later runs set it at 0.7 of the incumbent's own pace).
- Candidate `urn:kk:provider:anomaly-feed-head` (Haiku's change: skip a pass while the change feed has not
  moved since the last one): 11/11 analyser contract cases; 0.034 s against 0.154 s in the sandbox.
- After the switch, the verifier judged the three windows after the first (a warm-up it skips):
  0.079, 0.063, 0.055 s, within 0.12. Verdict: holds. `observed_after` in `run.json` holds only the
  warm-up window (0.147 s), the one observation there when the record was written.

The candidate wins by doing no work when nothing changed, not by making a full pass faster. That is
sound (observations and limits change only through feed entries), and it is also what a mean step time
rewards most. A benchmark that also reports the time of a full pass would tell the two apart.
