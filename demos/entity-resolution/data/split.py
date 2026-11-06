"""Write a dataset's inputs and its two answer sets where the judge wants them: outside the repository.

    python data/split.py OUT [--dataset abt-buy]

Reads data/<dataset>/ (written by data/fetch.py) and writes:

    OUT/inputs/left.jsonl, right.jsonl    the records every run reads (morphogen.local.yaml: inputs)
    OUT/search/lefts.json, gold.json      the search split's answers, for probes and optimizers (search)
    OUT/holdout/lefts.json, gold.json     the held-out answers, for verdicts only (private)

The split is fixed: a left record is held out when the first byte of sha256(SALT + id) falls in the
last 30% of its range. Then prints the lines to put in morphogen.local.yaml.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SALT = "morphogen-er-v1:"
HOLDOUT = 0.3


def split_of(record_id: str) -> str:
    h = hashlib.sha256((SALT + record_id).encode()).digest()[0] / 256
    return "holdout" if h >= 1 - HOLDOUT else "search"


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--dataset", default="abt-buy")
    a = ap.parse_args()
    src = HERE / a.dataset
    if not src.exists():
        sys.exit(f"no data for {a.dataset}: run python data/fetch.py {a.dataset}")
    out = Path(a.out).expanduser().resolve()
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=HERE, capture_output=True, text=True)
    if top.returncode == 0 and out.is_relative_to(Path(top.stdout.strip()).resolve()):
        sys.exit(f"{out} is inside the repository; the judge needs the answers outside it")
    left, right, gold = load(src / "left.jsonl"), load(src / "right.jsonl"), load(src / "gold.jsonl")
    (out / "inputs").mkdir(parents=True, exist_ok=True)
    for name, rows in (("left", left), ("right", right)):
        with open(out / "inputs" / f"{name}.jsonl", "w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    for split in ("search", "holdout"):
        ids = sorted(r["id"] for r in left if split_of(r["id"]) == split)
        keep = set(ids)
        pairs = sorted([g["left"], g["right"]] for g in gold if g["left"] in keep)
        (out / split).mkdir(exist_ok=True)
        (out / split / "lefts.json").write_text(json.dumps(ids))
        (out / split / "gold.json").write_text(json.dumps(pairs))
        print(f"{split}: {len(ids)} left records, {len(pairs)} gold pairs", file=sys.stderr)
    cells = ("component:er", "component:matcher", "component:blocking", "component:backend", "speed")
    print("cells:")
    for c in cells:
        print(f"  {c}: {{inputs: {out / 'inputs'}, private: {out / 'holdout'}, search: {out / 'search'}}}")


if __name__ == "__main__":
    main()
