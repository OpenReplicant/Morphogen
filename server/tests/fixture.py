"""A throwaway git project with the slow-script sample committed on main.

Trials run with `sandbox: none` unless MORPHOGEN_TEST_SANDBOX names another
runner (docker or podman), so the same suites can be run inside a container.
Data lives in the project's SQLite database.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from morphogen import judge as judge_mod
from morphogen import project
from morphogen.config import load_config

TARGET = "targets/slow-script"
SANDBOX = os.environ.get("MORPHOGEN_TEST_SANDBOX", "none")


def scratch_stores(root: Path):
    """The lists and evidence log of a scratch project at `root`, through the public surface
    (project.stores), so the tests do not depend on how a backend stores them."""
    root.mkdir(parents=True, exist_ok=True)
    return project.stores(root, load_config(root))


def tamper_first_record(log):
    """Rewrite the first record behind the log's back, as someone with access to its storage would.

    The one place the tests know a storage format: a JSONL file (`log.path` is a file), or a SQLite
    table (`log.path` is `sqlite:///<file>#<table>`, guarded by triggers an attacker would drop first).
    """
    import json
    import sqlite3
    where = str(log.path)
    if where.startswith("sqlite:"):
        file, table = where.split(":///", 1)[1].rsplit("#", 1)
        con = sqlite3.connect(file)
        try:
            for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = ?",
                                       (table,)).fetchall():
                con.execute(f'DROP TRIGGER "{name}"')
            con.execute(f"UPDATE {table} SET raw = replace(raw, '\"claim\":\"a\"', '\"claim\":\"rewritten\"') "
                        "WHERE seq = 1")
            con.commit()
        finally:
            con.close()
        return
    path = Path(where)
    lines = path.read_text().splitlines()
    rec = json.loads(lines[0])
    rec["claim"] = "rewritten"
    lines[0] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n")


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class SampleProject:
    def __init__(self, trials_per_day: int = 0):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "proj"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "test")
        project.init_project(self.repo)
        project.install_sample(self.repo, "slow-script", None)
        cfg_file = self.repo / "morphogen.yaml"
        cfg_file.write_text(cfg_file.read_text().replace("sandbox: auto", f"sandbox: {SANDBOX}")
                            .replace("trials_per_day: 20", f"trials_per_day: {trials_per_day}"))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        self.cfg = load_config(self.repo)
        _, self.evidence = project.stores(self.repo, self.cfg)

    def path(self, rel):
        return self.repo / TARGET / rel

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

    def judge(self, candidate):
        return judge_mod.judge(self.repo, self.cfg, TARGET, "main", candidate, self.evidence)

    def original(self, rel):
        return self.path(rel).read_text()

    def close(self):
        project.database(self.repo, self.cfg).engine.dispose()
        shutil.rmtree(self.tmp)


FAST = '''"""Most frequent words in a text."""
from collections import Counter


def normalise(text):
    words = [w.strip(".,;:!?\\"'()[]").lower() for w in text.split()]
    return [w for w in words if w]


def top_words(text, k):
    counts = Counter(normalise(text))
    return sorted(counts.items(), key=lambda p: (-p[1], p[0]))[:k]
'''


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
