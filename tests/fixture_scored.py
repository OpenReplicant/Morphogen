"""Sample projects scored outside the candidate: a classifier with held-out answers, and the same
classifier inside a structure with a contract test."""

import json
import shutil
import tempfile
from pathlib import Path

from tests.fixture import Project, git, judge_mod


# --- a target scored outside the candidate: classify numbers against held-out labels

CLASSIFY = '''"""Label each number "high" or "low". THRESHOLD is the setting to tune."""
THRESHOLD = 10


def label(x):
    return "high" if x >= THRESHOLD else "low"
'''

CLASSIFY_BENCH = '''"""The workload: label the inputs and print one label per line. Part of the judge's harness."""
import json
from classify import label

for x in json.load(open("inputs.json")):
    print(label(x))
'''

CLASSIFY_SCORE = '''"""The scorer: reads the run's labels on stdin and the held-out answers from MORPHOGEN_PRIVATE.
Part of the judge's harness; runs outside the candidate."""
import json, os, sys

gold = json.load(open(os.path.join(os.environ["MORPHOGEN_PRIVATE"], "gold.json")))
got = sys.stdin.read().split()
right = sum(1 for g, x in zip(gold, got) if g == x)
print(json.dumps({"accuracy": right / len(gold)}))
'''

CLASSIFY_TEST = '''import unittest
from classify import label


class Labels(unittest.TestCase):
    def test_labels_are_high_or_low(self):
        self.assertIn(label(3), ("high", "low"))
        self.assertIn(label(300), ("high", "low"))


if __name__ == "__main__":
    unittest.main()
'''

INPUTS = list(range(0, 100, 3))
GOLD = ["high" if x >= 50 else "low" for x in INPUTS]


def classify_target(private: str) -> str:
    return f"""name: classify
harness: [bench.py, score.py, test_classify.py, inputs.json]
check: python -m unittest -q test_classify
measure:
  run: python bench.py
  warmup: 0
  repeats: 4
  max_repeats: 8
  same_output: false
  score: {{run: python score.py, private: {private}}}
  metrics:
    scored.accuracy: {{direction: higher, primary: true, min_improvement: 0.05, gain: absolute, aggregate: mean}}
timeout: 60
parameters:
  threshold: {{file: classify.py, name: THRESHOLD, owner: agent, range: [0, 100]}}
"""


class ScoredProject(Project):
    """A classifier scored outside the candidate, with the held-out answers outside the repository."""

    target = "targets/classify"

    def __init__(self, private_inside=False, search=False):
        self.private_dir = Path(tempfile.mkdtemp(prefix="morphogen-private-"))
        (self.private_dir / "gold.json").write_text(json.dumps(GOLD))
        private = "held-out" if private_inside else str(self.private_dir)
        spec = classify_target(private)
        self.search_dir = None
        if search:
            self.search_dir = Path(tempfile.mkdtemp(prefix="morphogen-search-"))
            (self.search_dir / "gold.json").write_text(json.dumps(GOLD))
            spec = spec.replace(f"private: {private}}}", f"private: {private}, search: {self.search_dir}}}")
        files = {"classify.py": CLASSIFY, "bench.py": CLASSIFY_BENCH, "score.py": CLASSIFY_SCORE,
                 "test_classify.py": CLASSIFY_TEST, "inputs.json": json.dumps(INPUTS),
                 "target.yaml": spec}
        if private_inside:
            files["held-out/gold.json"] = json.dumps(GOLD)
        super().__init__(files, sample=None)
        if private_inside:
            self.private_dir = self.path("held-out")

    def close(self):
        shutil.rmtree(self.private_dir, ignore_errors=True)
        if self.search_dir:
            shutil.rmtree(self.search_dir, ignore_errors=True)
        super().close()


# --- a structure around the classifier: `report` consumes the labels `classify` provides, and the
# `labels` interface has a contract test owned by the intent (not by the cell under change).

CONTRACT_TEST = '''import sys
import unittest

sys.path.insert(0, "targets/classify")
from classify import label  # noqa: E402


class LabelsContract(unittest.TestCase):
    """What report relies on: any number gets "high" or "low", negative ones included."""

    def test_every_number_gets_a_label(self):
        for x in (-5, 0, 3.5, 49, 50, 1000):
            self.assertIn(label(x), ("high", "low"))


if __name__ == "__main__":
    unittest.main()
'''

STRUCTURE = {
    "cells": {
        "app": {},
        "classify": {"parent": "app", "at": "targets/classify/classify.py", "measure": "targets/classify",
                     "provides": ["labels"]},
        "report": {"parent": "app", "consumes": ["labels"]},
    },
    "interfaces": {
        "labels": {"tests": ["python -m unittest -q contracts.test_labels"],
                   "files": ["contracts/test_labels.py", "contracts/__init__.py"]},
    },
}


class StructuredProject(ScoredProject):
    """The classifier inside a structure, with cells.yaml and the contract test committed on main."""

    def __init__(self):
        super().__init__()
        import yaml
        (self.repo / "cells.yaml").write_text(yaml.safe_dump(STRUCTURE, sort_keys=False))
        (self.repo / "contracts").mkdir()
        (self.repo / "contracts" / "__init__.py").write_text("")
        (self.repo / "contracts" / "test_labels.py").write_text(CONTRACT_TEST)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "structure and contract")

    def branch_files(self, name, files):
        """Commit a candidate whose files are paths relative to the repository root."""
        git(self.repo, "checkout", "-q", "-B", name, "main")
        for rel, text in files.items():
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", name)
        git(self.repo, "checkout", "-q", "main")
        return name

    def judge_cell(self, candidate, cell="classify"):
        return judge_mod.judge(self.repo, self.cfg, self.target, "main", candidate, self.evidence, cell=cell)

    def judge_path(self, candidate, target=None):
        """Judge by the target's directory, without naming the cell."""
        return judge_mod.judge(self.repo, self.cfg, target or self.target, "main", candidate, self.evidence)
