"""The scorer: reads the run's labels on stdin and the held-out answers from MORPHOGEN_PRIVATE.
Part of the judge's harness; runs outside the candidate."""
import json, os, sys

gold = json.load(open(os.path.join(os.environ["MORPHOGEN_PRIVATE"], "gold.json")))
got = sys.stdin.read().split()
right = sum(1 for g, x in zip(gold, got) if g == x)
print(json.dumps({"accuracy": right / len(gold)}))
