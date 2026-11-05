"""A sample system with a cell inside it, sharing code: improving the cell can slow the whole."""

from tests.fixture import Project


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

def guard_cells() -> dict:
    """`system` (the whole, measured by its bench) and `fast` inside it (its own bench); both use
    compute.py, which only `fast` may change."""
    timing = {"run": "python bench.py", "better": {"wall_seconds": {"lower": True, "min": 0.10}},
              "rounds": {"warmup": 1, "repeats": 6, "max_repeats": 14}, "timeout": 120}
    return {"system": {"dir": "targets/system", **timing},
            "fast": {"in": "system", "dir": "targets/system/cell", "change": "targets/system/compute.py", **timing}}


GUARD_STRUCTURE = {"cells": guard_cells(), "interfaces": {}}


class GuardedProject(Project):
    """targets/system (the system's bench) and targets/system/cell (the cell's), sharing compute.py."""

    home = "targets/system/cell"
    cell = "fast"

    def __init__(self, cells=None):
        super().__init__(sample=None, cells=cells or guard_cells(), root_files={
            "targets/system/compute.py": COMPUTE, "targets/system/bench.py": SYSTEM_BENCH,
            "targets/system/cell/bench.py": CELL_BENCH})
