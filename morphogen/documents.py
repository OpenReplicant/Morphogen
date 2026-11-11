"""The documents people write and git versions, and the one way they are read.

`morphogen.yaml`'s settings (trunk, sandbox, budget), and the target spec a cell compiles to (how
the judge scores it; see project.py for the cell format the operator writes). Each has a schema;
`load` reads a file, checks it and returns plain data, or raises DocumentError naming the file and
every problem. Schemas check structure and types; what a value means is checked where it is used,
by the judge. Unknown keys are kept.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError



class DocumentError(ValueError):
    def __init__(self, path: Path | str, problems: list[str]):
        self.path, self.problems = str(path), problems
        super().__init__(f"{path}: " + "; ".join(problems))


class _Doc(BaseModel):
    model_config = ConfigDict(extra="allow")


# morphogen.yaml

class Budget(_Doc):
    trials_per_day: int | None = None
    probes_per_day: int | None = None


class Config(_Doc):
    trunk: str = "main"
    sandbox: Literal["auto", "podman", "docker", "none"] = "auto"
    sandbox_image: str = "python:3.12-slim"
    budget: Budget | None = None


# the target spec (compiled from a cell)

class Metric(_Doc):
    direction: Literal["lower", "higher"] = "lower"
    primary: bool = False
    min_improvement: float | None = None
    max_regression: float | None = None
    gain: Literal["relative", "absolute"] = "relative"
    aggregate: Literal["median", "mean"] = "median"


class Observer(_Doc):
    """observers.py: `command` (run, after each run) or `otel` (a receiver in the judge; metrics:)."""
    type: Literal["command", "otel"] = "command"
    run: str | None = None
    collected: str | None = None
    settle_ms: int | None = None
    export_interval_ms: int | None = None
    metrics: dict[str, dict[str, Any]] = {}


class Score(_Doc):
    """Scores each timed run's output outside the candidate: `run` comes from the base commit, runs in
    the base's directory in its own process, reads the run's output on stdin and prints its metrics
    as JSON (they become scored.*). `private` is a directory outside the repository, such as held-out
    gold answers; only the scorer is told where it is (MORPHOGEN_PRIVATE). `search`, if given, is what
    probes score against instead, so the search never sees the held-out answers."""
    run: str
    private: str | None = None
    search: str | None = None   # answers for probes (the optimizer's inner evaluator); `private` stays for verdicts


class Measure(_Doc):
    run: str
    warmup: int | None = None
    repeats: int | None = None
    max_repeats: int | None = None
    same_output: bool = True
    observer: Observer | None = None
    score: Score | None = None
    metrics: dict[str, Metric] = {}


class Equivalence(_Doc):
    gen: str | None = None
    run: str | None = None
    cases: int | None = None


class Target(_Doc):
    name: str | None = None
    description: str | None = None
    interface: str = "direct"  # direct | simulated; the judge checks it and what follows from it
    simulates: str | None = None
    check: str | None = None
    equivalence: Equivalence | None = None
    measure: Measure | None = None
    timeout: int | None = None
    # Guarantees the runner must provide for this target to be judged at all (runner.GUARANTEES).
    requires: list[Literal["network_isolated", "read_only_tree", "private_paths_hidden", "fresh_state",
                           "resource_limits"]] = []


SCHEMAS: dict[str, type[BaseModel]] = {"config": Config, "target": Target}


def _problems(e: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in err['loc']) or '(top)'}: {err['msg']}" for err in e.errors()]


def validate(kind: str, data: Any, path: Path | str = "<data>") -> dict:
    try:
        doc = SCHEMAS[kind].model_validate({} if data is None else data)
    except ValidationError as e:
        raise DocumentError(path, _problems(e)) from None
    return doc.model_dump(by_alias=True, exclude_none=True)


def load(kind: str, path: Path) -> dict:
    path = Path(path)
    try:
        text = path.read_text()
    except OSError as e:
        raise DocumentError(path, [f"cannot read: {e.strerror or e}"]) from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise DocumentError(path, [f"not valid YAML: {e}"]) from None
    return validate(kind, data, path)


def load_config(root: Path) -> dict:
    """morphogen.yaml at the project root, or the defaults, with the operator's morphogen.local.yaml
    (uncommitted) laid over it: `sandbox`, `sandbox_image` and `budget` override, and `cells` (held-out
    answer paths per cell: `private`, `search`), `env`, `services` and `gateway` (serve.py) are kept under `local`."""
    from .project import local_config
    f = Path(root) / "morphogen.yaml"
    cfg = load("config", f) if f.exists() else validate("config", {})
    local = local_config(root)
    for k in LOCAL_SETTINGS:
        if k in local:
            cfg[k] = local[k]
    cfg = validate("config", cfg, f)
    cfg["local"] = {"cells": local.get("cells") or {}, "settings": {k: local[k] for k in LOCAL_SETTINGS if k in local},
                    **{k: local[k] for k in LOCAL_SERVED if local.get(k)}}
    return cfg


LOCAL_SETTINGS = ("sandbox", "sandbox_image", "budget")
LOCAL_SERVED = ("env", "services", "gateway")   # what runs are given beyond their tree (serve.py); only ever the operator's
JUDGE_SETTINGS = ("trunk", "sandbox", "sandbox_image", "budget")


def rules_config(repo: Path, sha: str, cfg: dict) -> dict:
    """The settings a judged run uses: morphogen.yaml as committed at `sha` (the base), with the operator's
    morphogen.local.yaml laid over it, never the working copy. `cfg` is load_config's result; what it read
    from the local file is kept (cfg["local"]), what it read from the working copy is dropped. The result
    says where each setting came from (`settings_from`)."""
    import subprocess
    r = subprocess.run(["git", "show", f"{sha}:morphogen.yaml"], cwd=repo, capture_output=True, text=True)
    try:
        data = yaml.safe_load(r.stdout) if r.returncode == 0 else {}
    except yaml.YAMLError as e:
        raise DocumentError(f"{sha[:12]}:morphogen.yaml", [f"not valid YAML: {e}"]) from None
    base = validate("config", {k: v for k, v in (data or {}).items() if k in JUDGE_SETTINGS}, f"{sha[:12]}:morphogen.yaml")
    local = (cfg.get("local") or {}).get("settings") or {}
    out = validate("config", {**base, **local}, f"{sha[:12]}:morphogen.yaml + morphogen.local.yaml")
    out["local"] = cfg.get("local") or {"cells": {}, "settings": {}}
    where = (cfg.get("local") or {}).get("from") or "morphogen.local.yaml"
    out["settings_from"] = {k: (where if k in local else "base" if k in (data or {}) else "default")
                            for k in JUDGE_SETTINGS}
    return out


def settings_of(cfg: dict) -> dict:
    """The judge's settings, as a verdict records them."""
    return {k: cfg[k] for k in JUDGE_SETTINGS if k in cfg}
