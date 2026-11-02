---
name: hill-climb
description: Greedy best-of-N from the trunk. Try a few different approaches in parallel, adopt the best one that passes, repeat.
when: One clear bottleneck; the first rounds on any target.
weak_when: Every single step looks worse even though a sequence of steps would be better (a local optimum).
---

# hill-climb

**Parent:** the tip of the trunk.

**Candidates:** two or three genuinely different approaches to the located
gap, in sourcing order (reuse, configure, compose, generate). Different means
different families (for example "use a hash map" and "sort and scan"), not
two versions of the same idea. Label each with its family.

**After:** propose the best passing candidate (largest primary gain; on a tie,
the smaller diff) to the operator. Record the failures and their reasons; do
not retry a failed family on the same gap without a new reason.

**Stop:** when a round produces no pass, report what was tried. Auto selection
switches strategy after four trials in a row without a pass.
