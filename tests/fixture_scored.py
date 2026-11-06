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
                 settings=None, files=None, drop=(), local_extra=None):
        self.private_dir = Path(tempfile.mkdtemp(prefix="morphogen-private-"))
        (self.private_dir / "gold.json").write_text(json.dumps(GOLD))
        self.search_dir = None
        local = {"private": "targets/classify/held-out" if private_inside else str(self.private_dir)}
        if search:
            self.search_dir = Path(tempfile.mkdtemp(prefix="morphogen-search-"))
            (self.search_dir / "gold.json").write_text(json.dumps(GOLD))
            local["search"] = str(self.search_dir)
        extra = files
        files = {"classify.py": CLASSIFY, "bench.py": CLASSIFY_BENCH, "score.py": CLASSIFY_SCORE,
                 "test_classify.py": CLASSIFY_TEST, "inputs.json": json.dumps(INPUTS)}
        if private_inside:
            files["held-out/gold.json"] = json.dumps(GOLD)
        files = {k: v for k, v in {**files, **(extra or {})}.items() if k not in drop}
        local.update(local_extra or {})
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


# --- the same classifier with its inputs outside the repository (named in morphogen.local.yaml as
# `inputs`, read-only to every run), as for data whose licence keeps it out of git.

INPUTS_BENCH = '''"""The workload, reading its inputs from the directory the judge names (MORPHOGEN_INPUTS)."""
import json, os
from classify import label

for x in json.load(open(os.path.join(os.environ["MORPHOGEN_INPUTS"], "inputs.json"))):
    print(label(x))
'''


class InputsProject(ScoredProject):
    """ScoredProject whose inputs live outside the repository, named in morphogen.local.yaml."""

    def __init__(self):
        self.inputs_dir = Path(tempfile.mkdtemp(prefix="morphogen-inputs-"))
        (self.inputs_dir / "inputs.json").write_text(json.dumps(INPUTS))
        super().__init__(files={"bench.py": INPUTS_BENCH}, drop=("inputs.json",),
                         local_extra={"inputs": str(self.inputs_dir)})

    def inputs_at(self, where: str):
        """Say in morphogen.local.yaml that the inputs are somewhere else."""
        import yaml
        local = yaml.safe_load((self.repo / "morphogen.local.yaml").read_text())
        local["cells"]["classify"]["inputs"] = where
        self.set_local(local)

    def close(self):
        shutil.rmtree(self.inputs_dir, ignore_errors=True)
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


# --- a text cell: the reply in reply.txt is the whole thing that may change; the scorer counts which
# held-out words it contains.

REPLY_BENCH = 'print(open("reply.txt").read())\n'

REPLY_SCORE = '''"""The scorer: the share of the held-out words (MORPHOGEN_PRIVATE/words.json) in the run's output."""
import json, os, sys

words = json.load(open(os.path.join(os.environ["MORPHOGEN_PRIVATE"], "words.json")))
got = set(sys.stdin.read().lower().split())
print(json.dumps({"coverage": sum(w in got for w in words) / len(words)}))
'''

REPLY_TEST = '''import unittest


class Reply(unittest.TestCase):
    def test_it_is_short(self):
        self.assertLessEqual(len(open("reply.txt").read().split()), 12)


if __name__ == "__main__":
    unittest.main()
'''

WORDS = ["hello", "world", "morphogen"]


class TextProject(Project):
    """One text cell: `reply.txt` may change (and nothing else); its output is scored against
    held-out words kept outside the repository."""

    home = "targets/reply"
    cell = "reply"

    def __init__(self):
        self.private_dir = Path(tempfile.mkdtemp(prefix="morphogen-private-"))
        (self.private_dir / "words.json").write_text(json.dumps(WORDS))
        cell = {"description": "A one-line reply that greets the world and names the project, Morphogen, "
                               "in at most 12 words.",
                "dir": "targets/reply", "change": "targets/reply/reply.txt", "run": "python bench.py",
                "better": {"coverage": {"higher": True, "min": 0.1, "gain": "absolute", "aggregate": "mean"}},
                "score": "python score.py", "tests": "python -m unittest -q test_reply",
                "rounds": {"warmup": 0, "repeats": 4, "max_repeats": 8}, "timeout": 60}
        super().__init__({"reply.txt": "hi there\n", "bench.py": REPLY_BENCH, "score.py": REPLY_SCORE,
                          "test_reply.py": REPLY_TEST}, sample=None, cells={"reply": cell},
                         local={"cells": {"reply": {"private": str(self.private_dir),
                                                    "search": str(self.private_dir)}}})

    def close(self):
        shutil.rmtree(self.private_dir, ignore_errors=True)
        super().close()
