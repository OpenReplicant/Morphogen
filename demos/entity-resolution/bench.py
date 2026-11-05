"""Measure a backend on a benchmark split: link each left record to the right records it names.

    python bench.py [--dataset amazon-google] [--split search] [--backend tfidf]

Prints one JSON line: precision, recall, f1 and counts. Run time is not reported here: the judge
measures it from outside the process.

The split is fixed: a left record is in `holdout` when the first byte of sha256(SALT + id) falls
in the last 30% of its range, otherwise in `search`. Optimizers and builders use `search` only;
`holdout` is for the judge. Nothing here enforces that yet: the judge, once built, keeps the
held-out gold pairs where a candidate cannot read them.
"""

import argparse
import hashlib
import json
from pathlib import Path

from er import BACKENDS, make, settings

HERE = Path(__file__).resolve().parent
SALT = "morphogen-er-v1:"
HOLDOUT = 0.3


def split_of(record_id: str) -> str:
    h = hashlib.sha256((SALT + record_id).encode()).digest()[0] / 256
    return "holdout" if h >= 1 - HOLDOUT else "search"


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run(dataset: str, split: str, backend: str) -> dict:
    d = HERE / "data" / dataset
    if not d.exists():
        raise SystemExit(f"no data for {dataset}: run python data/fetch.py {dataset}")
    left = [r for r in load(d / "left.jsonl") if split_of(r["id"]) == split]
    right = load(d / "right.jsonl")
    keep = {r["id"] for r in left}
    gold = {(g["left"], g["right"]) for g in load(d / "gold.jsonl") if g["left"] in keep}

    r = make(backend)
    for rec in right:
        r.add(rec)
    predicted = set()
    for rec in left:
        found = r.resolve(rec)
        if found:
            for rid in r.members[found[0][0]]:
                predicted.add((rec["id"], rid))

    tp = len(predicted & gold)
    p = tp / len(predicted) if predicted else 0.0
    rc = tp / len(gold) if gold else 0.0
    f1 = 2 * p * rc / (p + rc) if p + rc else 0.0
    return {"dataset": dataset, "split": split, "backend": backend, "f1": round(f1, 4),
            "precision": round(p, 4), "recall": round(rc, 4), "left": len(left), "right": len(right),
            "gold_pairs": len(gold), "predicted_pairs": len(predicted), "true_positives": tp}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="amazon-google")
    ap.add_argument("--split", default="search", choices=["search", "holdout"])
    ap.add_argument("--backend", default=settings.BACKEND, choices=sorted(BACKENDS))
    a = ap.parse_args()
    print(json.dumps(run(a.dataset, a.split, a.backend)))
