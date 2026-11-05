"""Optimizers, behind one interface, and `tune`: search a target's agent-owned parameters.

An optimizer proposes values; Morphogen writes each proposal onto a branch, scores it with a probe
(the cheap inner evaluator: practice, never a verdict), and sends only the best to the judge, which
scores it on the held-out cases with full statistics. GEPA, Optuna or a Claude Code worker plug in
by implementing `Optimizer`; the built-in ones need only the standard library.
"""

from __future__ import annotations

import itertools
import json
import random
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from . import judge as judge_mod


@dataclass
class Trial:
    values: dict[str, Any]
    branch: str
    gain: float | None           # the probe's median gain on the primary metric; None if refused
    probe: dict = field(repr=False, default_factory=dict)


class Optimizer(Protocol):
    name: str

    def propose(self, space: dict[str, dict], history: list[Trial]) -> dict[str, Any] | None:
        """The next values to try (a subset of the space's parameters), or None when done."""


def _levels(p: dict, steps: int) -> list[Any]:
    if p.get("choices") is not None:
        return list(p["choices"])
    lo, hi = p["range"]
    if float(lo).is_integer() and float(hi).is_integer() and isinstance(p.get("_value"), int):
        n = int(hi) - int(lo)
        return sorted({int(lo) + round(n * i / (steps - 1)) for i in range(steps)}) if n >= steps else \
            list(range(int(lo), int(hi) + 1))
    return [lo + (hi - lo) * i / (steps - 1) for i in range(steps)]


class Grid:
    """Every combination of each parameter's choices, or `steps` evenly spaced values in its range."""
    name = "grid"

    def __init__(self, steps: int = 5):
        self.steps, self._it = steps, None

    def propose(self, space, history):
        if self._it is None:
            names = sorted(space)
            self._it = (dict(zip(names, combo))
                        for combo in itertools.product(*(_levels(space[n], self.steps) for n in names)))
        return next(self._it, None)


class RandomSearch:
    """Values drawn at random within each parameter's range or choices."""
    name = "random"

    def __init__(self, trials: int = 10, seed: int | None = None):
        self.trials, self.rng = trials, random.Random(seed)

    def propose(self, space, history):
        if len(history) >= self.trials:
            return None
        out = {}
        for n, p in space.items():
            if p.get("choices") is not None:
                out[n] = self.rng.choice(p["choices"])
            else:
                lo, hi = p["range"]
                out[n] = self.rng.randint(int(lo), int(hi)) if isinstance(p.get("_value"), int) \
                    else self.rng.uniform(lo, hi)
        return out


OPTIMIZERS = {"grid": Grid, "random": RandomSearch}


# --- writing a value where the judge will read it


def write_parameter(tree_dir: Path, p: dict, value: Any) -> None:
    f = tree_dir / p["file"]
    text = f.read_text()
    if p.get("name"):
        pattern = re.compile(rf"^{re.escape(p['name'])}\s*(:[^=]*)?=.*$", re.M)
        matches = list(pattern.finditer(text))
        if not matches:
            raise LookupError(f"no module-level {p['name']} in {p['file']}")
        m = matches[-1]  # the judge reads the last assignment
        f.write_text(text[:m.start()] + f"{p['name']}{m.group(1) or ' '}= {value!r}" + text[m.end():])
        return
    if f.suffix == ".toml":
        raise LookupError("writing TOML keys is not supported yet; use a YAML or JSON file, or a Python constant")
    data = json.loads(text) if f.suffix == ".json" else yaml.safe_load(text)
    node, parts = data, p["key"].split(".")
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value
    f.write_text(json.dumps(data, indent=2) + "\n" if f.suffix == ".json" else yaml.safe_dump(data, sort_keys=False))


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def space_of(spec: dict, tree_dir: Path) -> dict[str, dict]:
    """The agent-owned parameters with a range or choices: what an optimizer may search."""
    out = {}
    for n, p in (spec.get("parameters") or {}).items():
        if p.get("owner") == "agent" and (p.get("range") is not None or p.get("choices") is not None):
            out[n] = {**p, "_value": judge_mod._read_parameter(tree_dir, p)}
    return out


def tune(root: Path, cfg: dict, target: str, optimizer: Optimizer, evidence, base: str = "main",
         rounds: int = 2, max_trials: int = 50) -> dict:
    """Search the target's agent-owned parameters with `optimizer`; probe every proposal; judge the best."""
    repo = judge_mod.repo_root(root)
    rel = (Path(root) / target).resolve().relative_to(repo)
    base_sha = judge_mod.resolve(repo, base)
    trials: list[Trial] = []
    with tempfile.TemporaryDirectory(prefix="morphogen-tune-") as tmp:
        work = Path(tmp) / "w"
        _git(repo, "worktree", "add", "--detach", "--quiet", str(work), base_sha)
        try:
            spec = judge_mod.load_spec(work, rel)
            space = space_of(spec, work / rel)
            if not space:
                raise judge_mod.JudgeError("no agent-owned parameters with a range or choices in target.yaml")
            metrics = judge_mod._check_spec(spec)
            primary = next(k for k, v in metrics.items() if v.get("primary"))
            while len(trials) < max_trials:
                values = optimizer.propose({k: dict(v) for k, v in space.items()}, trials)
                if values is None:
                    break
                if all(values.get(k) == space[k]["_value"] for k in values):
                    continue  # the base's own values: nothing to try
                _git(work, "checkout", "--quiet", "--detach", base_sha)
                for k, v in values.items():
                    write_parameter(work / rel, space[k], v)
                branch = f"morphogen/tune/{rel.name}/{optimizer.name}-{len(trials) + 1}"
                _git(work, "checkout", "--quiet", "-B", branch)
                _git(work, "commit", "--quiet", "-am", f"tune {rel.name}: " + ", ".join(f"{k}={v!r}" for k, v in values.items()))
                pr = judge_mod.probe(repo, cfg, str(rel), branch, evidence, base=base_sha, cases=1, rounds=rounds)
                gain = None if pr.get("forbidden") or pr.get("parameter_violations") or \
                    not (pr.get("check") or {"passed": True}).get("passed", True) \
                    else (pr.get("metrics") or {}).get(primary, {}).get("gain")
                trials.append(Trial(values, branch, gain, pr))
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(work)], cwd=repo, capture_output=True)
    scored = [t for t in trials if t.gain is not None]
    best = max(scored, key=lambda t: t.gain, default=None)
    out = {"target": str(rel), "optimizer": optimizer.name, "primary": primary,
           "trials": [{"values": t.values, "branch": t.branch, "probe_gain": t.gain} for t in trials]}
    if best is None or best.gain <= 0:
        out["verdict"] = None
        out["note"] = "no proposal improved on the base in probes; nothing sent to the judge"
        return out
    v = judge_mod.judge(repo, cfg, str(rel), base_sha, best.branch, evidence,
                        {"optimizer": optimizer.name, "values": json.dumps(best.values, sort_keys=True)})
    out.update({"best": {"values": best.values, "branch": best.branch, "probe_gain": best.gain},
                "verdict": v["verdict"], "judge": v})
    return out
