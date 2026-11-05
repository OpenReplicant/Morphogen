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


# --- a system with a cell inside it, sharing code: improving the cell can slow the whole.

COMPUTE = '''"""Shared by the system and the cell. Both functions return the sum of squares below n."""
N = 300000


def fast_path(n):
    return sum(i * i for i in range(n))


def other(n):
    return n * (n - 1) * (2 * n - 1) // 6
'''

SYSTEM_BENCH = '''from compute import N, fast_path, other
print(fast_path(N), other(N))
'''

CELL_BENCH = '''import sys
sys.path.insert(0, "..")
from compute import N, fast_path  # noqa: E402
print(fast_path(N))
'''

GUARD_TARGET = '''name: {name}
harness: [bench.py]
measure:
  run: python bench.py
  warmup: 1
  repeats: 6
  max_repeats: 14
  metrics:
    wall_seconds: {{direction: lower, primary: true, min_improvement: 0.10}}
timeout: 120
'''

GUARD_STRUCTURE = {
    "cells": {
        "system": {"measure": "targets/system"},
        "fast": {"parent": "system", "at": "targets/system/compute.py#fast_path", "measure": "targets/system/cell"},
    },
    "interfaces": {},
}


class GuardedProject(Project):
    """targets/system (the root's measure) and targets/system/cell (the cell's), sharing compute.py."""

    target = "targets/system/cell"

    def __init__(self):
        super().__init__({}, sample=None)
        import yaml
        files = {"targets/system/compute.py": COMPUTE, "targets/system/bench.py": SYSTEM_BENCH,
                 "targets/system/target.yaml": GUARD_TARGET.format(name="system"),
                 "targets/system/cell/bench.py": CELL_BENCH,
                 "targets/system/cell/target.yaml": GUARD_TARGET.format(name="fast-path"),
                 "cells.yaml": yaml.safe_dump(GUARD_STRUCTURE, sort_keys=False)}
        for rel, text in files.items():
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "system and cell")

    def branch_root(self, name, files):
        git(self.repo, "checkout", "-q", "-B", name, "main")
        for rel, text in files.items():
            (self.repo / rel).write_text(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", name)
        git(self.repo, "checkout", "-q", "main")
        return name

    def judge_cell(self, candidate, cell="fast"):
        return judge_mod.judge(self.repo, self.cfg, self.target, "main", candidate, self.evidence, cell=cell)


# --- an agent-like target measured by OpenTelemetry: the harness reports cost and requests over
# OTLP/HTTP JSON, as Claude Code does with CLAUDE_CODE_ENABLE_TELEMETRY=1, honouring the same
# exporter variables. The candidate's agent.py decides how many steps (model calls) it takes.

AGENT = '''"""The agent's plan. STEPS model calls; fewer is cheaper."""
STEPS = 10


def plan():
    return STEPS
'''

AGENT_BENCH = '''"""The workload: run the agent, and report its usage over OTLP/HTTP JSON (part of the harness)."""
import json, os, urllib.request
from agent import plan


def attrs(d):
    return [{"key": k, "value": {"stringValue": str(v)}} for k, v in d.items()]


steps = plan()
print(steps)
if os.environ.get("CLAUDE_CODE_ENABLE_TELEMETRY") == "1":
    res = {"resource": {"attributes": attrs(dict(kv.split("=", 1) for kv in
                                                 os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "").split(",") if kv))}}
    end = os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]

    def post(path, body):
        urllib.request.urlopen(urllib.request.Request(end + path, json.dumps(body).encode(),
                                                      {"Content-Type": "application/json"}), timeout=5).read()

    if os.environ.get("OTEL_METRICS_EXPORTER", "none") != "none":
        points = [{"asDouble": 0.01, "attributes": attrs({"model": "m"})} for _ in range(steps)]
        tokens = [{"asInt": "100", "attributes": attrs({"type": "output"})} for _ in range(steps)]
        post("/v1/metrics", {"resourceMetrics": [{**res, "scopeMetrics": [{"metrics": [
            {"name": "claude_code.cost.usage", "unit": "USD",
             "sum": {"dataPoints": points, "aggregationTemporality": 1, "isMonotonic": True}},
            {"name": "claude_code.token.usage", "unit": "tokens",
             "sum": {"dataPoints": tokens, "aggregationTemporality": 1, "isMonotonic": True}}]}]}]})
    if os.environ.get("OTEL_LOGS_EXPORTER", "none") != "none":
        recs = [{"body": {"stringValue": "claude_code.api_request"},
                 "attributes": attrs({"event.name": "api_request", "duration_ms": 120})} for _ in range(steps)]
        post("/v1/logs", {"resourceLogs": [{**res, "scopeLogs": [{"logRecords": recs}]}]})
'''

AGENT_TARGET = '''name: agent
harness: [bench.py]
measure:
  run: python bench.py
  warmup: 0
  repeats: 4
  max_repeats: 8
  same_output: false
  observer:
    type: otel
    collected: outside
    settle_ms: 150
    metrics:
      cost_usd: {metric: claude_code.cost.usage}
      output_tokens: {metric: claude_code.token.usage, where: {type: output}}
      api_requests: {event: claude_code.api_request, count: true}
      api_ms: {event: claude_code.api_request, field: duration_ms}
  metrics:
    observed.cost_usd: {direction: lower, primary: true, min_improvement: 0.10}
timeout: 60
parameters:
  steps: {file: agent.py, name: STEPS, owner: agent, range: [1, 20]}
'''


class AgentProject(Project):
    target = "targets/agent"

    def __init__(self):
        super().__init__({"agent.py": AGENT, "bench.py": AGENT_BENCH, "target.yaml": AGENT_TARGET}, sample=None)
