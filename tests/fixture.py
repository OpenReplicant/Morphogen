"""Throwaway git projects with sample targets committed on main.

Trials run with `sandbox: none` unless MORPHOGEN_TEST_SANDBOX names another runner (docker or
podman), so the same suites can run inside a container.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from morphogen import judge as judge_mod
from morphogen.documents import load_config
from morphogen.evidence import Evidence

HERE = Path(__file__).resolve().parent
TARGET = "targets/slow-script"
SANDBOX = os.environ.get("MORPHOGEN_TEST_SANDBOX", "none")


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class Project:
    """A git repository with one target directory copied in and committed on main."""

    target = TARGET

    def __init__(self, files: dict[str, str] | None = None, sample: str | None = "slow-script",
                 trials_per_day: int = 0):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "proj"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "test")
        if sample:
            shutil.copytree(HERE / "fixtures" / sample, self.repo / self.target)
        for rel, text in (files or {}).items():
            p = self.path(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        (self.repo / "morphogen.yaml").write_text(
            f"sandbox: {SANDBOX}\nbudget: {{trials_per_day: {trials_per_day}}}\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        self.cfg = load_config(self.repo)
        self.evidence = Evidence.for_project(self.repo)

    def path(self, rel):
        return self.repo / self.target / rel

    def branch(self, name, files=None, delete=()):
        """Commit a candidate on `name`: files maps target-relative paths to new text."""
        git(self.repo, "checkout", "-q", "-B", name, "main")
        for rel, text in (files or {}).items():
            p = self.path(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        for rel in delete:
            self.path(rel).unlink()
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", name)
        git(self.repo, "checkout", "-q", "main")
        return name

    def on_main(self, files):
        git(self.repo, "checkout", "-q", "main")
        for rel, text in files.items():
            p = self.path(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base: " + ", ".join(sorted(files)))

    def judge(self, candidate, labels=None):
        return judge_mod.judge(self.repo, self.cfg, self.target, "main", candidate, self.evidence, labels)

    def original(self, rel):
        return self.path(rel).read_text()

    def close(self):
        shutil.rmtree(self.tmp)


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


def observed_project(collected, primary=True):
    """The sample project with an observer; its latency is the primary metric unless primary=False."""
    p = SampleProject()
    p.path("observe.py").write_text(OBSERVER)
    spec = p.path("target.yaml")
    text = spec.read_text().replace("harness: [bench.py, gen.py, test_topwords.py]",
                                    "harness: [bench.py, gen.py, test_topwords.py, observe.py]")
    if primary:
        text = text.replace("    wall_seconds: {direction: lower, primary: true, min_improvement: 0.10}",
                            "    wall_seconds: {direction: lower}\n"
                            "    observed.latency_ms: {direction: lower, primary: true, min_improvement: 0.10}")
    else:
        text = text.replace("    wall_seconds: {direction: lower, primary: true, min_improvement: 0.10}",
                            "    wall_seconds: {direction: lower, primary: true, min_improvement: 0.10}\n"
                            "    observed.latency_ms: {direction: lower}")
    text = text.replace("  metrics:\n", f"  observer: {{run: python observe.py, collected: {collected}}}\n  metrics:\n", 1)
    spec.write_text(text)
    git(p.repo, "add", "-A")
    git(p.repo, "commit", "-q", "-m", "observe latency")
    return p


SETTINGS = "\n# Settings the judge reads (see target.yaml parameters).\nCHUNK = 64\nLIMIT = 1000\n"
PARAMETERS_YAML = """
parameters:
  chunk:
    file: topwords.py
    name: CHUNK
    owner: agent
    range: [16, 256]
  limit:
    file: topwords.py
    name: LIMIT
    owner: operator
"""


def parameter_project() -> "SampleProject":
    p = SampleProject()
    p.on_main({"topwords.py": p.original("topwords.py") + SETTINGS,
               "target.yaml": p.original("target.yaml") + PARAMETERS_YAML})
    return p


# The other sample projects, re-exported so tests import them from one place.
from tests.fixture_scored import *  # noqa: E402,F401,F403
from tests.fixture_system import *  # noqa: E402,F401,F403
from tests.fixture_agent import *  # noqa: E402,F401,F403
