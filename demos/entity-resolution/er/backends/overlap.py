"""Overlap coefficient on token sets (shared tokens over the smaller set): the simplest backend, and
the baseline. Unlike Jaccard it does not penalise one name for being a longer form of the other."""

from ..base import Base


class Overlap(Base):
    def score(self, a: list[str], b: list[str]) -> float:
        sa, sb = set(a), set(b)
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / min(len(sa), len(sb))
