# RCAEval experiments (T12, R5-28)

Every statistic tried on the analyser, with its numbers. RE1 is the tuning set; RE2 (OB, TT) is held out (D-64).
Avg@5 mean over the fault types; windows of 60 s, 600 s either side of the injection. Methods `analyser`,
`robust` and `baro` are `run.py` (results in `runs/`); the rest are `variants.py` (results only here).

Floor (rebuild 4 `kernel-w60`): re1-ob 0.894, re1-ss 0.922, re1-tt 0.800, re2-ob 0.935, re2-tt 0.643.

## What the floor measures

Rebuild 4's floor is not its analyser. It is an eval-only statistic (`eval/rcaeval/packs.py` `robust_z`):
each metric's largest median/IQR z-score of the windows after the injection against all the windows before
it, with fallbacks for a flat baseline (standard deviation, else a tenth of the median, else 1). Rebuild 4's
analyser (`modules/anomaly/anomaly/detect.py`) used the mean/standard-deviation z-score over its previous
windows, the same as ours before R5-28, and was never measured on RCAEval.

## RE1 (tuning)

| Method | What it is | OB | SS | TT |
|---|---|---|---|---|
| robust (`run.py`) | rebuild 4's statistic, ported unchanged, scores rounded to 0.1 | 0.886 | 0.922 | 0.802 |
| r4-unrounded | the same without rounding | 0.886 | 0.922 | not run |
| baro (`run.py`) | RCAEval's BARO, a published baseline | not run | 0.576 | 0.262 |
| analyser-nofb (`run.py`, before R5-28) | the analyser's z-score (mean, sd; no score when sd is 0) over its sliding history of up to 20 windows | 0.874 | 0.864 | 0.702 |
| robust-slide | median/IQR over the sliding history (else sd, else a tenth of the median; no score when all are 0) | 0.890 | 0.854 | 0.668 |
| mean-excl | analyser-nofb; windows scored above 3 left out of later history | 0.852 | 0.860 | 0.672 |
| robust-excl | robust, the same exclusion | 0.858 | 0.832 | 0.614 |
| mean-fb10 | the analyser's z-score; a flat history scaled by a tenth of its mean (none when the mean is 0) | 0.874 | 0.866 | 0.702 |
| robust-fb | median/IQR with all of rebuild 4's fallbacks, over the sliding history | 0.890 | 0.920 | 0.774 |
| **mean-fb = analyser (`run.py`, R5-28)** | the analyser's z-score with rebuild 4's flat-history fallbacks (a tenth of the mean, else 1) | **0.874** | **0.914** | **0.788** |

Chosen on RE1: mean-fb, the best of the analyser's own statistic (no lower than analyser-nofb anywhere, +0.050
on SS, +0.086 on TT), and the fallback chain the floor's statistic already used. robust-fb is higher on OB and
SS but lower on TT, and would replace the analyser's statistic rather than fix its blind spot.

## RE2 (held out, measured once per method)

Order, so the hold-out can be judged: the analyser before the change and `robust` were measured on RE2 first
(RE2-OB 0.930, just under the floor, was known); the change was then chosen on the RE1 numbers above
(`variants.py` ran only on RE1), and RE2 measured once with it. RE2-TT was first unpacked onto a full disk and
held 55 of its 90 cases; it was downloaded again and every method rerun on all 90 (numbers below).

| Method | OB (90 cases) | TT (90 cases) |
|---|---|---|
| floor (rebuild 4; its RE2-TT had 63 of 90 cases, D-65 d) | 0.935 | 0.643 |
| robust (rebuild 4's statistic, ported) | 0.935 | 0.667 |
| analyser-nofb (before R5-28) | 0.930 | 0.773 |
| **analyser (R5-28)** | **0.942** | **0.773** |

The change gains 0.012 on RE2-OB and nothing on RE2-TT.

## Notes

- Rebuild 4's D-65(b) calls a scale of 1 for a baseline flat at 0 a bug ("scores it in raw units (bytes) and
  drowns every other signal"), yet `packs.robust_z` still ends in `or 1.0`, and the floor was measured with it.
  R5-28 keeps it and says so: without it (mean-fb10) the analyser gains nothing.
- Why the analyser missed: with no spread in its history it gave no score, so a metric flat before the fault
  that then jumps was never flagged. mean-fb10 gains nothing, so the whole gain comes from histories flat at
  exactly 0, scored with a scale of 1 (TT `ts-auth-service_cpu/1`: rebuild 4's top hit is that service's
  memory cache, flat, then about 2 MB more). The same blind spot holds in production: a count at 0 that starts
  climbing. The scale of 1 depends on the metric's unit (0 to 4 bytes is flagged, 0 to 0.9 of a CPU is not);
  rebuild 4's statistic has the same dependence.
- The ported `robust` matches rebuild 4 on RE1-SS, RE1-TT and RE2-OB; on RE1-OB it gives 0.886 (0.894), and on
  all 90 RE2-TT cases 0.667 (0.643 on 63). The RCAEval package is identical to the pinned commit; rounding changes nothing.
  The RE1-OB gap is unexplained; rebuild 4's packs.py may have changed after that run.
- The remaining RE1 gap (0.008 to 0.020) is the history: the analyser compares a window with the 20 before
  it, which after the injection include faulty windows; rebuild 4's statistic compares every later window
  with the clean windows before the injection, which only an eval knows.
- Leaving anomalous windows out of later history lowers every score: the first window after the injection
  already has a clean history (the 10 windows before it), and exclusion removes normal-but-noisy windows.
- Contract case 07 (flat 0.05 then 0.06 is not unusual) still holds: score 2, under 3. Case 14 pins the new
  rule (0.05 to 0.08 and 0 to 5 are unusual, 0 to 2 is not); three new mutants fail it.
