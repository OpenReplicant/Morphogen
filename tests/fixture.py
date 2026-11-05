"""Throwaway git projects in the cell format (one morphogen.yaml), committed on main.

Trials run with `sandbox: none` unless MORPHOGEN_TEST_SANDBOX names another runner (docker or
podman), so the same suites can run inside a container.
"""

import copy
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

from morphogen import judge as judge_mod
from morphogen.documents import load_config
from morphogen.evidence import Evidence

HERE = Path(__file__).resolve().parent
TARGET = "targets/slow-script"
SANDBOX = os.environ.get("MORPHOGEN_TEST_SANDBOX", "none")


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


# The sample: a correct but quadratic word counter. solve.py and topwords.py may change; the bench, the
# input generator and the tests are the judge's.
SLOW_CELL = {
    "description": "Most frequent words in a text. Correct but quadratic; make it faster without changing results.",
    "dir": TARGET,
    "change": [f"{TARGET}/solve.py", f"{TARGET}/topwords.py"],
    "run": "python bench.py",
    "better": {"wall_seconds": {"lower": True, "min": 0.10},
               "max_rss_kb": {"lower": True, "max_regression": 0.50}},
    "tests": "python -m unittest -q test_topwords",
    "same_as_base": {"gen": "python gen.py {seed} 3000", "run": "python solve.py", "cases": 5},
    "rounds": {"warmup": 1, "repeats": 10, "max_repeats": 30},
    "timeout": 120,
}


class Project:
    """A git repository with morphogen.yaml (`cells`, `interfaces`) and files, committed on main.

    `home` is the directory `path()` and `branch()` resolve against (the judged cell's `dir`); `cell`
    is the cell judged by default. `local` is written to the uncommitted morphogen.local.yaml."""

    home = TARGET
    cell = "slow-script"

    def __init__(self, files: dict[str, str] | None = None, sample: str | None = "slow-script",
                 trials_per_day: int = 0, cells: dict | None = None, interfaces: dict | None = None,
                 local: dict | None = None, root_files: dict[str, str] | None = None):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "proj"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "test")
        if sample:
            shutil.copytree(HERE / "fixtures" / sample, self.repo / self.home)
        for rel, text in (files or {}).items():
            self._write(self.path(rel), text)
        for rel, text in (root_files or {}).items():
            self._write(self.repo / rel, text)
        if cells is None:
            cells = {self.cell: copy.deepcopy(SLOW_CELL)}
        self.doc_ = {"sandbox": SANDBOX, "budget": {"trials_per_day": trials_per_day}, "cells": cells}
        if interfaces:
            self.doc_["interfaces"] = interfaces
        self._write(self.repo / "morphogen.yaml", yaml.safe_dump(self.doc_, sort_keys=False))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        (self.repo / ".git" / "info" / "exclude").write_text("morphogen.local.yaml\n")
        self.set_local(local or {})
        self.evidence = Evidence.for_project(self.repo)

    @property
    def target(self):
        return f"cell:{self.cell}"

    @staticmethod
    def _write(p: Path, text: str):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def set_local(self, local: dict):
        f = self.repo / "morphogen.local.yaml"
        if local:
            f.write_text(yaml.safe_dump(local))
        elif f.exists():
            f.unlink()
        self.cfg = load_config(self.repo)

    def path(self, rel):
        return self.repo / self.home / rel

    def doc(self) -> dict:
        """A copy of morphogen.yaml as committed on main."""
        return copy.deepcopy(self.doc_)

    def dump(self, doc: dict) -> str:
        return yaml.safe_dump(doc, sort_keys=False)

    def branch(self, name, files=None, delete=(), root=False, links=None, base="main"):
        """Commit a candidate on `name`. `files` and `delete` are paths relative to `home`, or to the
        repository root with root=True; `links` maps a path to a symlink target."""
        at = self.repo if root else self.repo / self.home
        git(self.repo, "checkout", "-q", "-B", name, base)
        for rel, text in (files or {}).items():
            self._write(at / rel, text)
        for rel in delete:
            (at / rel).unlink()
        for rel, to in (links or {}).items():
            p = at / rel
            if p.exists() or p.is_symlink():
                p.unlink()
            p.symlink_to(to)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", name)
        git(self.repo, "checkout", "-q", "main")
        return name

    def branch_files(self, name, files, **kw):
        """A candidate whose files are paths relative to the repository root."""
        return self.branch(name, files, root=True, **kw)

    branch_root = branch_files

    def on_main(self, files=None, doc=None, root=False):
        """Commit on main: files (relative to `home`, or the root), and a new morphogen.yaml."""
        git(self.repo, "checkout", "-q", "main")
        at = self.repo if root else self.repo / self.home
        for rel, text in (files or {}).items():
            self._write(at / rel, text)
        if doc is not None:
            self.doc_ = copy.deepcopy(doc)
            self._write(self.repo / "morphogen.yaml", self.dump(doc))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base: " + ", ".join(sorted(files or {}) or ["morphogen.yaml"]))
        self.cfg = load_config(self.repo)

    def judge(self, candidate, labels=None, target=None, base="main"):
        return judge_mod.judge(self.repo, self.cfg, target or self.target, base, candidate, self.evidence, labels)

    def judge_cell(self, candidate, cell=None):
        return self.judge(candidate, target=f"cell:{cell or self.cell}")

    def judge_path(self, candidate, target=None):
        """Judge by a directory (default the cell's), without naming the cell."""
        return self.judge(candidate, target=target or self.home)

    def original(self, rel):
        return self.path(rel).read_text()

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


SampleProject = Project


FAST = '''"""Most frequent words in a text."""
from collections import Counter


def normalise(text):
    words = [w.strip(".,;:!?\\"'()[]").lower() for w in text.split()]
    return [w for w in words if w]


def top_words(text, k):
    counts = Counter(normalise(text))
    return sorted(counts.items(), key=lambda p: (-p[1], p[0]))[:k]
'''

WRONG = FAST.replace(")[:k]", ")[:max(k - 1, 0)]")

OBSERVER = '''import json, os
# Stands in for a query to a telemetry backend: the run's latency, from the
# time window the judge passed in (collected outside the code under test).
start, end = float(os.environ["MORPHOGEN_RUN_START"]), float(os.environ["MORPHOGEN_RUN_END"])
assert os.environ["MORPHOGEN_RUN_ID"] and os.environ["MORPHOGEN_SIDE"] in ("base", "candidate", "measured")
print(json.dumps({"latency_ms": (end - start) * 1000}))
'''


def observed_cell(collected, primary=True) -> dict:
    cell = copy.deepcopy(SLOW_CELL)
    cell["observe"] = {"run": "python observe.py", "collected": collected}
    if primary:
        cell["better"] = {"observed.latency_ms": {"lower": True, "min": 0.10}, "wall_seconds": "lower"}
    else:
        cell["better"] = {"wall_seconds": {"lower": True, "min": 0.10}, "observed.latency_ms": "lower"}
    return cell


def observed_project(collected, primary=True):
    """The sample with an observer (a harness file); its latency is the primary metric unless primary=False."""
    return Project({"observe.py": OBSERVER}, cells={"slow-script": observed_cell(collected, primary)})


SETTINGS = "\n# Settings the judge reads (see morphogen.yaml).\nCHUNK = 64\nLIMIT = 1000\n"


def parameter_project() -> "Project":
    cell = copy.deepcopy(SLOW_CELL)
    cell["change"].append(f"{TARGET}/topwords.py#CHUNK in 16..256")
    cell["keep"] = f"{TARGET}/topwords.py#LIMIT"
    p = Project(cells={"slow-script": cell})
    p.on_main({"topwords.py": p.original("topwords.py") + SETTINGS})
    return p


# The other sample projects, re-exported so tests import them from one place.
from tests.fixture_scored import *  # noqa: E402,F401,F403
from tests.fixture_system import *  # noqa: E402,F401,F403
from tests.fixture_agent import *  # noqa: E402,F401,F403
