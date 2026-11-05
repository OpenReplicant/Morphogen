"""From the old format (target.yaml in each target directory, plus cells.yaml) to the cell format.

The result allows exactly what the old format allowed: every file in a target's directory that is
not a harness file becomes a `change` path, each agent-owned parameter a ranged setting and every
other parameter a `keep`. That is wider than most cells need; the operator narrows `change` after.
Held-out paths (`measure.score.private`, `search`) go to morphogen.local.yaml, never to the
committed file. Removed with the old format, after the project's own files have moved.
"""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

import yaml

from . import documents
from .project import FILE, Project
from .structure import Structure

OPTIONS = {"min_improvement": "min", "max_regression": "max_regression", "gain": "gain",
           "aggregate": "aggregate"}
DEFAULTS = {"gain": "relative", "aggregate": "median"}


def _ls(root: Path, rel: Path) -> list[str]:
    out = subprocess.run(["git", "ls-files", "--", str(rel)], cwd=root, capture_output=True, text=True,
                         check=True).stdout
    return sorted(line for line in out.splitlines() if line)


def _setting(base: PurePosixPath, p: dict) -> str:
    where = f"{base / p['file']}" + (f"#{p['name']}" if p.get("name") else f":{p['key']}")
    if p.get("range") is not None:
        lo, hi = p["range"]
        return f"{where} in {lo:g}..{hi:g}"
    if p.get("choices") is not None:
        return f"{where} in {yaml.safe_dump(list(p['choices']), default_flow_style=True).strip()}"
    return where


def _better(metrics: dict) -> dict:
    out = {}
    for name, m in sorted(metrics.items(), key=lambda kv: not kv[1].get("primary")):
        long = {m.get("direction", "lower"): True}
        long.update({OPTIONS[k]: v for k, v in m.items() if k in OPTIONS and v is not None and DEFAULTS.get(k) != v})
        out[name] = long
    return out


def _target_cell(root: Path, rel: Path, spec: dict) -> tuple[dict, dict]:
    base = PurePosixPath(rel.as_posix())
    harness = {str(base / h) for h in spec.get("harness", [])} | {str(base / "target.yaml")}
    change = [f for f in _ls(root, rel) if f not in harness]
    keep = []
    for p in (spec.get("parameters") or {}).values():
        (change if p.get("owner") == "agent" else keep).append(_setting(base, p))
    m = spec.get("measure") or {}
    cell: dict = {"dir": str(base), "change": change}
    if keep:
        cell["keep"] = keep
    if spec.get("description"):
        cell["description"] = spec["description"]
    cell["run"] = m["run"]
    cell["better"] = _better(m.get("metrics") or {})
    if spec.get("check"):
        cell["tests"] = spec["check"]
    sc = m.get("score") or {}
    if sc.get("run"):
        cell["score"] = sc["run"]
    if m.get("observer"):
        cell["observe"] = "otel" if m["observer"] == {"type": "otel"} else m["observer"]
    if spec.get("equivalence"):
        cell["same_as_base"] = spec["equivalence"]
    if m.get("same_output", True) != (not sc.get("run")):
        cell["same_output"] = m.get("same_output", True)
    rounds = {k: m[k] for k in ("warmup", "repeats", "max_repeats") if m.get(k) is not None}
    if rounds:
        cell["rounds"] = rounds
    for k in ("timeout", "simulates", "requires"):
        if spec.get(k):
            cell[k] = spec[k]
    local = {k: sc[k] for k in ("private", "search") if sc.get(k)}
    for k, v in list(local.items()):
        if not Path(v).expanduser().is_absolute():   # relative to the target: make it relative to the root
            local[k] = str(base / v)
    return cell, local


def migrate(root: Path, cfg: dict, targets: list[str] | None = None) -> tuple[dict, dict]:
    """(the new morphogen.yaml, the new morphogen.local.yaml) for the project at `root`."""
    root = Path(root)
    f = root / FILE
    raw = (yaml.safe_load(f.read_text()) or {}) if f.exists() else {}
    doc = {k: v for k, v in raw.items() if k != "structure"}   # keep only what the operator wrote
    cells: dict = {}
    interfaces: dict = {}
    srel = Path(cfg.get("structure", "cells.yaml"))
    s = Structure.load(root / srel) if (root / srel).exists() else None
    sbase = PurePosixPath(srel.parent.as_posix())
    prefix = "" if sbase == PurePosixPath(".") else f"cd {sbase} && "
    measured: dict[str, str] = {}
    if s is not None:
        for n, c in s.cells.items():
            cell: dict = {}
            if c.parent:
                cell["in"] = c.parent
            for k in ("provides", "consumes"):
                v = getattr(c, k)
                if v:
                    cell[k] = v[0] if len(v) == 1 else list(v)
            if c.guard is not None:
                cell["guard"] = c.guard
            change, keep = [], []
            for p in c.parameters.values():
                d = p.model_dump(exclude_none=True)
                (change if d["owner"] == "agent" else keep).append(_setting(sbase, d))
            if change:
                cell["change"] = change
            if keep:
                cell["keep"] = keep
            cells[n] = cell
            if c.measure:
                for d in (root / srel.parent / c.measure, root / c.measure):
                    if (d / "target.yaml").exists():
                        measured[str(d.resolve().relative_to(root.resolve()))] = n
                        break
        for n, i in s.interfaces.items():
            tests = [prefix + t for t in i.tests]
            entry = tests[0] if len(tests) == 1 else tests
            interfaces[n] = {"tests": entry, "external": i.external} if i.external else entry
    local: dict = {"cells": {}}
    for t in targets or []:
        rel = Path(t)
        if str(rel) not in measured:
            measured[str(rel)] = Path(t).name
    for rel, name in sorted(measured.items()):
        spec = documents.load("target", root / rel / "target.yaml")
        new, priv = _target_cell(root, Path(rel), spec)
        old = cells.setdefault(name, {})
        merged = {**old, **new}
        merged["change"] = new["change"] + [x for x in old.get("change", []) if x not in new["change"]]
        if old.get("keep") or new.get("keep"):
            merged["keep"] = list(dict.fromkeys(new.get("keep", []) + old.get("keep", [])))
        cells[name] = merged
        if priv:
            local["cells"][name] = priv
    doc["cells"] = cells
    if interfaces:
        doc["interfaces"] = interfaces
    Project.from_dict(doc)   # what we write must load
    return doc, (local if local["cells"] else {})


def dump(doc: dict) -> str:
    return yaml.safe_dump(doc, sort_keys=False, default_flow_style=False, width=110)


__all__ = ["migrate", "dump", "FILE"]
