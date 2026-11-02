---
name: archive-search
description: Open-ended search over every judged variant, not only the trunk, after the Darwin Gödel Machine. Build on promising and under-explored variants, including ones that failed.
when: Hill-climbing has stalled; a better design may need a step that does not pay off alone.
weak_when: The archive is nearly empty; there is nothing to choose from yet.
---

# archive-search

**Parent:** read `archive(target)`. Score each variant by its primary gain
(failed or negative counts as zero) plus a bonus for having few children
(`children` in the archive). Pick two or three parents by that score, at least
one of them not the trunk. A failed variant is eligible when its reasons show
a near miss, for example a gain just under the bar, or a single wrong output
from an otherwise promising approach.

**Candidates:** one change per parent, built on that parent's commit (a
worker branches from the parent, not the trunk). Label each with
`strategy: archive-search`, its family and `parent: <commit>`.

**Judging:** judge each candidate against its **parent** first, to see whether
the step helped. Only a candidate that also passes against the **trunk** can be
proposed for merging.

**After:** propose the best variant that passes against the trunk. Keep the
rest in the archive; they are the stepping stones for later rounds.

**Stop:** after two rounds without a step that improves on its parent, report
the most promising lineage to the operator.
