"""Naming a target: a directory with a target.yaml, or `cell:NAME` for a cell's `measure`.

    resolve(root, cfg, "targets/classify")  -> ("targets/classify", None)
    resolve(root, cfg, "cell:classify")     -> ("targets/classify", "classify")

The cell's measure is looked up in the project's structure (morphogen.yaml `structure`, default
cells.yaml) as it is now, to find the directory. Judging a cell then reads the structure again from
the base commit, which is what the verdict rests on.
"""

from __future__ import annotations

from pathlib import Path

from .structure import Structure

PREFIX = "cell:"


def resolve(root: Path, cfg: dict, target: str) -> tuple[str, str | None]:
    if not target.startswith(PREFIX):
        return target, None
    name = target[len(PREFIX):]
    rel = Path(cfg.get("structure", "cells.yaml"))
    s = Structure.load(Path(root) / rel)
    cell = s.cells.get(name)
    if cell is None:
        raise KeyError(f"no cell {name!r} in the structure")
    if not cell.measure:
        raise KeyError(f"cell {name!r} has no measure (a directory with target.yaml)")
    sdir = Path(root) / rel.parent
    for candidate in (sdir / cell.measure, Path(root) / cell.measure):
        if (candidate / "target.yaml").exists():
            return str(candidate.resolve().relative_to(Path(root).resolve())), name
    return str(rel.parent / cell.measure), name
