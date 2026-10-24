# G2 gate run, 2026-10-24: a candidate built by Haiku, under T7's checks

`KK_G2_BUILDER=harness`, with `claude -p` on Haiku as the builder (prompt: `xacce4724309a/prompt.md`,
its output: `harness.log`). The run used the checks of R5-22 and R5-23: the harness without the record's
credentials, the slot's own runner, service cases, full passes timed by the sandbox, the incumbent's
login, the content hash on the approved step, a telemetry token per service. G2 passed.

- Incumbent `urn:kk:provider:anomaly`: observed at 0.160 s a pass; the person's limit 0.112 s (0.7 of it).
- Candidate `urn:kk:provider:anomaly-newest`. Haiku's change: a pass reads only the newest 23
  observations of each target (all the rule compares), and looks up status for those alone, falling
  back to reading everything when one of them is deprecated or not numeric. It passed 11/11 rule cases
  and 11/11 service cases; its full pass, timed by the sandbox, took 0.087 s against 0.131 s.
- After the switch, the verifier judged three windows after the warm-up: 0.080, 0.100, 0.083 s, within
  0.112. Verdict: holds.

**The candidate has a bug the 11 cases did not cover.** It takes the newest 23 observations per target,
but the rule compares each target *and property*: a target reporting two properties gets about half the
history for each, so its z-scores differ from the incumbent's. Case 12
(`two-properties-each-full-history`) was added after this run. The incumbent and the CI fixture pass
it; this candidate fails it as a service case (11/12). Had a person reviewed this replacement, the
diff (`partition by c.subject`) is where it shows.

Haiku's own summary says it could not run the benchmark or the SQL (no database in its workdir); the
sandbox did both.
