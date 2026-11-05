"""A sample system with a cell inside it, sharing code: improving the cell can slow the whole."""

from tests.fixture import Project, git, judge_mod


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

    def judge_path(self, candidate, target=None):
        """Judge by the target's directory, without naming the cell."""
        return judge_mod.judge(self.repo, self.cfg, target or self.target, "main", candidate, self.evidence)
