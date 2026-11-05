"""TF-IDF cosine similarity over tokens, with document frequencies from the known records: rare
tokens (model codes, product names) weigh more than common ones (brands, "system", "black")."""

import math
from collections import Counter

from ..base import Base


class TfIdf(Base):
    def changed(self) -> None:
        self._idf_cache = {}

    def idf(self, t: str) -> float:
        cache = getattr(self, "_idf_cache", None)
        if cache is None:
            cache = self._idf_cache = {}
        if t not in cache:
            n = len(self.records)
            cache[t] = math.log((n + 1) / (len(self.index.get(t, ())) + 1)) + 1.0
        return cache[t]

    def vector(self, toks: list[str]) -> dict[str, float]:
        tf = Counter(toks)
        return {t: (1 + math.log(c)) * self.idf(t) for t, c in tf.items()}

    def score(self, a: list[str], b: list[str]) -> float:
        va, vb = self.vector(a), self.vector(b)
        dot = sum(w * vb.get(t, 0.0) for t, w in va.items())
        na = math.sqrt(sum(w * w for w in va.values()))
        nb = math.sqrt(sum(w * w for w in vb.values()))
        return dot / (na * nb) if na and nb else 0.0
