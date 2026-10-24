"""Re-ranking in kk.recall (D-66, R5-35), without a model: off unless KK_RERANK=1; with a stub cross-encoder,
subjects go in score order, each with its recalled claims, the claims past POOL keep their place, and a
subject's text (TEXTS) is what is scored. No database.

  python3 kernel/providers/tests/test_rerank.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from kk import recall  # noqa: E402


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg)


class Stub:
    """Scores a document by how often it says 'invoice'."""
    def __init__(self):
        self.seen = []

    def rerank(self, query, docs):
        self.seen = list(docs)
        return [d.count("invoice") for d in docs]


stub = Stub()
recall._models[(recall.RERANKER, False)] = stub      # as if fastembed and the model were there
os.environ.pop("KK_RERANK", None)
check(recall.reranker() is None, "without KK_RERANK=1 there is no re-ranking, even with the model there")
os.environ["KK_RERANK"] = "0"
check(recall.reranker() is None, "KK_RERANK=0: none")
os.environ["KK_RERANK"] = "1"
check(recall.reranker() is stub, "KK_RERANK=1: the cached cross-encoder")
claims = [{"subject": "urn:x:a", "object_value": {"@value": "a note"}},
          {"subject": "urn:x:b", "object_value": {"@value": "invoice"}},
          {"subject": "urn:x:a", "object_value": {"@value": "another note"}},
          {"subject": "urn:x:c", "object_value": {"@value": "invoice invoice"}}]
got = [c["object_value"]["@value"] for c in recall.rerank("invoices?", claims, 10)]
check(got == ["invoice invoice", "invoice", "a note", "another note"],
      "subjects in score order, each with its recalled claims in their order")
recall.rerank("invoices?", claims, 10, {"urn:x:a": "invoice invoice invoice"})
check(stub.seen[0] == "invoice invoice invoice", "a subject's text, when given, is what is scored")
got = recall.rerank("q", claims, 2)
check(len(got) == 2, "no more than the limit")
many = [{"subject": f"urn:x:{i}", "object_value": {"@value": "invoice" if i == recall.POOL + 1 else "x"}}
        for i in range(recall.POOL + 5)]
got = recall.rerank("q", many, recall.POOL + 5)
check(got[recall.POOL + 1]["subject"] == f"urn:x:{recall.POOL + 1}", "claims past POOL keep their place")
check(recall.rerank("q", claims[:1], 5) == claims[:1], "one claim: nothing to re-rank")
del recall._models[(recall.RERANKER, False)]
print("re-rank checks passed")
