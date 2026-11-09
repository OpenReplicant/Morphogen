"""The classifier in the cell format: one morphogen.yaml with the cells, their `change`, `run`,
`better` and `tests`, and the interfaces; the held-out answers named in an uncommitted
morphogen.local.yaml."""

import json
import shutil
import tempfile
from pathlib import Path

import yaml

from morphogen.documents import load_config
from morphogen.evidence import Evidence
from tests.fixture import SANDBOX, git, judge_mod
from tests.fixture_scored import (CLASSIFY, CLASSIFY_BENCH, CLASSIFY_SCORE, CLASSIFY_TEST, CONTRACT_TEST,
                                  GOLD, INPUTS)

CELLS_CONTRACT = CONTRACT_TEST.replace("targets/classify", "classify")


def cells_doc(code: bool = False) -> dict:
    """`code`: the classifier's whole file may change, except LIMIT; otherwise only THRESHOLD, in 0..100."""
    classify = {
        "in": "app",
        "dir": "classify",
        "change": "classify/classify.py" if code else "classify/classify.py#THRESHOLD in 0..100",
        "run": "python bench.py",
        "better": {"accuracy": {"higher": True, "min": 0.05, "gain": "absolute", "aggregate": "mean"}},
        "score": "python score.py",
        "tests": "python -m unittest -q test_classify",
        "rounds": {"warmup": 0, "repeats": 4, "max_repeats": 8},
        "timeout": 60,
        "provides": "labels",
    }
    if code:
        classify["keep"] = "classify/classify.py#LIMIT"
    return {
        "sandbox": SANDBOX,
        "budget": {"trials_per_day": 0},
        "cells": {"app": {}, "classify": classify, "report": {"in": "app", "consumes": "labels"}},
        "interfaces": {"labels": "python -m unittest -q contracts.test_labels"},
    }


class CellsProject:
    """A git repository on main with the classifier described in morphogen.yaml."""

    target = "cell:classify"

    def __init__(self, code: bool = False, search: bool = False):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "proj"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "test")
        self.private_dir = Path(tempfile.mkdtemp(prefix="morphogen-private-"))
        (self.private_dir / "gold.json").write_text(json.dumps(GOLD))
        files = {
            "classify/classify.py": CLASSIFY + ("LIMIT = 100\n" if code else ""),
            "classify/bench.py": CLASSIFY_BENCH,
            "classify/score.py": CLASSIFY_SCORE,
            "classify/test_classify.py": CLASSIFY_TEST,
            "classify/inputs.json": json.dumps(INPUTS),
            "contracts/__init__.py": "",
            "contracts/test_labels.py": CELLS_CONTRACT,
            "morphogen.yaml": yaml.safe_dump(cells_doc(code), sort_keys=False),
        }
        for rel, text in files.items():
            self.write(rel, text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        local = {"cells": {"classify": {"private": str(self.private_dir)}}}
        if search:
            local["cells"]["classify"]["search"] = str(self.private_dir)
        self.write("morphogen.local.yaml", yaml.safe_dump(local))   # never committed
        (self.repo / ".git" / "info" / "exclude").write_text("morphogen.local.yaml\n")
        self.cfg = load_config(self.repo)
        self.evidence = Evidence.for_project(self.repo)

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def branch(self, name, files=None, delete=(), links=None):
        """Commit a candidate: `files` and `delete` are repository paths; `links` maps a path to a
        symlink target."""
        git(self.repo, "checkout", "-q", "-B", name, "main")
        for rel, text in (files or {}).items():
            self.write(rel, text)
        for rel in delete:
            (self.repo / rel).unlink()
        for rel, to in (links or {}).items():
            p = self.repo / rel
            if p.exists() or p.is_symlink():
                p.unlink()
            p.symlink_to(to)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", name)
        git(self.repo, "checkout", "-q", "main")
        return name

    def judge(self, candidate, target=None):
        return judge_mod.judge(self.repo, self.cfg, target or self.target, "main", candidate, self.evidence)

    def change(self, candidate):
        """A change that claims no improvement, judged by the base's rules (judge.judge_change)."""
        return judge_mod.judge_change(self.repo, self.cfg, "main", candidate, self.evidence)

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.private_dir, ignore_errors=True)
