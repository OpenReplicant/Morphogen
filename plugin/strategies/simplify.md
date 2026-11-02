---
name: simplify
description: Shrink a passing change to the smallest version that clears the same bar, in the spirit of delta debugging.
when: A pass changes more than it needs to; before proposing a large change for merging.
weak_when: The passing change is already small.
---

# simplify

**Parent:** the passing variant named in the strategy's reason (not yet merged,
larger than about 20 changed lines). Read its diff against its base.

**Candidates:** two or three smaller versions built from the **trunk**, each
keeping only part of the change: drop helpers, revert incidental edits, keep
the core idea. Label each with `strategy: simplify` and `parent: <the passing
commit>`.

**Judging:** against the trunk, like any candidate.

**After:** among the passing versions, propose the smallest diff whose primary
gain is within a few points of the original. If none passes, propose the
original and say that it could not be reduced.

**Stop:** after one round.
