# Statistics

The judge compares the candidate with its base **case by case**. For each KPI and case it takes the
per-case improvement `d = candidate - base` (or `base - candidate` when lower is better), so positive is
always better.

- **A deciding KPI passes** when an exact one-sided sign test rejects "no better" at the policy's
  `alpha`, and the mean improvement reaches the card's floor.
- **A bounding KPI passes** when a paired bootstrap lower bound (10,000 resamples, one-sided, 1 - alpha)
  on the mean improvement is no worse than minus the card's tolerance.
- **Short runs.** If the base's run saw fewer cases than the set has, judgment stops (`stop`): that is
  the judge's failure. If the candidate's run is short, the candidate is refused. Extra cases a
  candidate invents are ignored.

## Minimum detectable effect

Stated from the case count before anything runs. The sign test can only reject when at least
`k = ceil(log2(1/alpha))` cases improve (5 at alpha 0.05), so no candidate can show an effect smaller
than k of the N cases. For a 0/1 KPI such as accuracy that is k/N in its own units: with 30 cases at
alpha 0.05, 0.167. The verdict records it as `mde`.

## A/A

Identical code must not pass. 2,000 trials of a noisy program against itself, 40 cases, alpha 0.05:
**3.45%** passed, within the 5% the exact test promises (`tests/test_stats.py::test_a_a_rate`). Any
change to the statistics must rerun this.

## What is not done

There is no extend-while-undecided rule: each verdict sees one fixed case set, so no correction for
repeated looks is needed. Adding one would need a sequential correction and a new A/A run.

The judge's randomness (the bootstrap seed) is drawn by the trusted job and recorded, never derived
from anything the author chooses, such as a commit hash an author could grind for a lucky seed.
