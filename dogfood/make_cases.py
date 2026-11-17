"""Generate the dogfood's held-out cases from a secret seed. The generator is public; without the seed
the cases and answers are not. Run only by .github/workflows/morphogen-seed-cases.yml.

    python3 dogfood/make_cases.py --seed-env SEED --out DIR
"""

import argparse
import json
import os
import random
from collections import Counter
from pathlib import Path

WORDS = "apple banana cherry delta echo fox golf hotel india juliet kilo lima".split()


def reference(text, k):
    counts = Counter(text.lower().split())
    return [w for w, _ in sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:k]]


def make_cases(seed):
    rnd = random.Random(seed)
    rows = []
    for i in range(10):
        text = " ".join(rnd.choice(WORDS) for _ in range(rnd.randint(20, 60)))
        rows.append({"id": f"easy-{i}", "input": {"text": text, "k": 3}})
    for i in range(20):
        text = " ".join(rnd.choice([w, w.upper(), w.title()])
                        for w in (rnd.choice(WORDS) for _ in range(rnd.randint(20, 60))))
        rows.append({"id": f"mixed-{i}", "input": {"text": text, "k": 3}})
    for r in rows:
        r["answer"] = reference(r["input"]["text"], r["input"]["k"])
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-env", required=True)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    seed = os.environ[a.seed_env]
    if len(seed) < 32:
        raise SystemExit("the seed must be at least 32 characters")
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "cases.jsonl").write_text("".join(json.dumps(c) + "\n" for c in make_cases(seed)))
    (a.out / "served").write_text("0\n")
    print(f"wrote {len(make_cases(seed))} cases")
