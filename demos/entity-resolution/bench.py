"""The workload: resolve every left record against the right records, and print the pairs found.

    python bench.py [--backend tfidf]

Reads left.jsonl and right.jsonl from the directory the judge names (MORPHOGEN_INPUTS), or from
DATA (default data/abt-buy) when run by hand. Prints one predicted pair per line, `left<TAB>right`,
sorted. It computes no score: score.py does, from the base, against answers this process cannot
read. By hand:

    python data/split.py ~/er-split
    MORPHOGEN_INPUTS=~/er-split/inputs python bench.py | MORPHOGEN_PRIVATE=~/er-split/search python score.py
"""

import argparse
import json
import os
from pathlib import Path

from er import BACKENDS, make, settings

HERE = Path(__file__).resolve().parent


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def predict(data: Path, backend: str) -> list[tuple[str, str]]:
    r = make(backend)
    for rec in load(data / "right.jsonl"):
        r.add(rec)
    pairs = set()
    for rec in load(data / "left.jsonl"):
        found = r.resolve(rec)
        if found:
            for rid in r.members[found[0][0]]:
                pairs.add((rec["id"], rid))
    return sorted(pairs)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default=settings.BACKEND, choices=sorted(BACKENDS))
    a = ap.parse_args()
    data = Path(os.environ.get("MORPHOGEN_INPUTS") or os.environ.get("DATA") or HERE / "data" / "abt-buy")
    for left, right in predict(data, a.backend):
        print(f"{left}\t{right}")
