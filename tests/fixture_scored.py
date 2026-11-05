"""Sample projects scored outside the candidate: a classifier with held-out answers, and the same
classifier inside a structure with a contract test."""

import copy
import json
import shutil
import tempfile
from pathlib import Path

from tests.fixture import Project


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


CLASSIFY_CELL = {
    "dir": "targets/classify",
    "change": ["targets/classify/classify.py", "targets/classify/classify.py#THRESHOLD in 0..100"],
    "run": "python bench.py",
    "better": {"accuracy": {"higher": True, "min": 0.05, "gain": "absolute", "aggregate": "mean"}},
    "score": "python score.py",
    "tests": "python -m unittest -q test_classify",
    "rounds": {"warmup": 0, "repeats": 4, "max_repeats": 8},
    "timeout": 60,
}


class ScoredProject(Project):
    """A classifier scored outside the candidate, with the held-out answers outside the repository
    (named in the uncommitted morphogen.local.yaml)."""

    home = "targets/classify"
    cell = "classify"

    def __init__(self, private_inside=False, search=False, cells=None, interfaces=None, root_files=None,
                 settings=None):
        self.private_dir = Path(tempfile.mkdtemp(prefix="morphogen-private-"))
        (self.private_dir / "gold.json").write_text(json.dumps(GOLD))
        self.search_dir = None
        local = {"private": "targets/classify/held-out" if private_inside else str(self.private_dir)}
        if search:
            self.search_dir = Path(tempfile.mkdtemp(prefix="morphogen-search-"))
            (self.search_dir / "gold.json").write_text(json.dumps(GOLD))
            local["search"] = str(self.search_dir)
        files = {"classify.py": CLASSIFY, "bench.py": CLASSIFY_BENCH, "score.py": CLASSIFY_SCORE,
                 "test_classify.py": CLASSIFY_TEST, "inputs.json": json.dumps(INPUTS)}
        if private_inside:
            files["held-out/gold.json"] = json.dumps(GOLD)
        super().__init__(files, sample=None, cells=cells or {"classify": copy.deepcopy(CLASSIFY_CELL)},
                         interfaces=interfaces, local={"cells": {"classify": local}}, root_files=root_files,
                         settings=settings)
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

def structure_cells() -> dict:
    """classify inside app, providing the labels that report consumes."""
    return {"app": {},
            "classify": {"in": "app", "provides": "labels", **copy.deepcopy(CLASSIFY_CELL)},
            "report": {"in": "app", "consumes": "labels"}}


STRUCTURE = {"cells": structure_cells(), "interfaces": {"labels": "python -m unittest -q contracts.test_labels"}}


class StructuredProject(ScoredProject):
    """The classifier inside a structure, with the `labels` contract test committed on main."""

    def __init__(self):
        super().__init__(cells=structure_cells(), interfaces=copy.deepcopy(STRUCTURE["interfaces"]),
                         root_files={"contracts/__init__.py": "", "contracts/test_labels.py": CONTRACT_TEST})
