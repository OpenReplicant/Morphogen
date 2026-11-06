"""The scorer: F1 of the predicted pairs (on stdin, `left<TAB>right`) for the left records of one split.

The judge runs it from the base, in its own process, with MORPHOGEN_PRIVATE naming a directory
outside the repository that holds the split's left ids (lefts.json) and its gold pairs (gold.json):
the held-out split for verdicts, the search split for probes. Pairs for left records outside the
split are ignored, so every run can resolve all left records. Prints one JSON object.
"""

import json
import os
import sys
from pathlib import Path

d = Path(os.environ["MORPHOGEN_PRIVATE"])
lefts = set(json.loads((d / "lefts.json").read_text()))
gold = {tuple(p) for p in json.loads((d / "gold.json").read_text())}
predicted = set()
for line in sys.stdin:
    parts = line.rstrip("\n").split("\t")
    if len(parts) == 2 and parts[0] in lefts:
        predicted.add((parts[0], parts[1]))
tp = len(predicted & gold)
p = tp / len(predicted) if predicted else 0.0
r = tp / len(gold) if gold else 0.0
f1 = 2 * p * r / (p + r) if p + r else 0.0
print(json.dumps({"f1": f1, "precision": p, "recall": r, "predicted": len(predicted)}))
