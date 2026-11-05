"""The optimizer slot: a catalog of optimizers behind one interface, and `tune`.

An optimizer proposes values for a target's agent-owned parameters; Morphogen writes each proposal
onto a branch, scores it with a probe (the cheap inner evaluator: practice, never a verdict), tells
the optimizer the result, and sends only the best proposal to the judge, which scores it on the
held-out cases with full statistics.

The catalog (`CATALOG`, `catalog()`):

- built in, standard library only: `grid`, `random`, `hillclimb`;
- adapters to other libraries, available when installed: `optuna` (TPE sampling);
- meta: `selector`, an optimizer whose policy chooses which member proposes next. Its first policy
  is `bandit` (UCB1 on probe gains, optionally primed by earlier verdicts): a fast, system-1 rule.
  A policy is anything with `choose(members, history) -> name`;
- planned, not built: `gepa` (reflective evolution of anything interpretable as text, using model
  calls; GEPA's own adapters are modular) and an `llm` selector policy, which could also search
  for and add optimizers to the catalog.

Other packages add optimizers through the `morphogen.optimizers` entry-point group: each entry
point names a factory returning an object with `name` and `propose`.
"""

from __future__ import annotations

import itertools
import json
import math
import random
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Protocol

import yaml

from . import judge as judge_mod


@dataclass
class Trial:
    values: dict[str, Any]
    branch: str
    gain: float | None           # the probe's median gain on the primary metric; None if refused or failed
    optimizer: str = ""          # which optimizer (or selector member) proposed it
    probe: dict = field(repr=False, default_factory=dict)


class Optimizer(Protocol):
    name: str

    def propose(self, space: dict[str, dict], history: list[Trial]) -> dict[str, Any] | None:
        """The next values to try (a subset of the space's parameters), or None when done. Each entry
        of `space` is the parameter's declaration plus `_value`, its value on the base."""

    # Optional: def observe(self, trial: Trial) -> None, called with each proposal's result.


def _is_int(p: dict) -> bool:
    lo, hi = p["range"]
    return isinstance(p.get("_value"), int) and float(lo).is_integer() and float(hi).is_integer()


def _levels(p: dict, steps: int) -> list[Any]:
    if p.get("choices") is not None:
        return list(p["choices"])
    lo, hi = p["range"]
    if _is_int(p):
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
        self.trials, self.rng, self.made = trials, random.Random(seed), 0

    def propose(self, space, history):
        if self.made >= self.trials:
            return None
        self.made += 1
        out = {}
        for n, p in space.items():
            if p.get("choices") is not None:
                out[n] = self.rng.choice(p["choices"])
            else:
                lo, hi = p["range"]
                out[n] = self.rng.randint(int(lo), int(hi)) if _is_int(p) else self.rng.uniform(lo, hi)
        return out


class HillClimb:
    """Coordinate ascent from the base's values: step each parameter up and down, move to the best
    improvement, and halve the step when nothing improves, until the step is below `min_step` of the
    range. Choices step to the neighbouring choice."""
    name = "hillclimb"

    def __init__(self, start_step: float = 0.25, min_step: float = 0.02, max_trials: int = 60):
        self.frac, self.min_frac, self.max_trials = start_step, min_step, max_trials
        self.center: dict | None = None
        self.best = 0.0           # probe gains are relative to the base, so the base scores 0
        self.queue: list[dict] = []
        self.batch: list[dict] = []
        self.made = 0

    def _neighbours(self, space):
        out = []
        for n, p in sorted(space.items()):
            v = self.center[n]
            if p.get("choices") is not None:
                ch = list(p["choices"])
                i = ch.index(v) if v in ch else 0
                cands = [ch[j] for j in (i - 1, i + 1) if 0 <= j < len(ch)]
            else:
                lo, hi = p["range"]
                step = (hi - lo) * self.frac
                if _is_int(p):
                    step = max(1, round(step))
                cands = [min(hi, max(lo, v + d)) for d in (step, -step)]
                cands = [round(c) if _is_int(p) else c for c in cands]
            for c in cands:
                if c != v:
                    out.append({**self.center, n: c})
        return out

    def _settle(self, history):
        """Move to the best result of the last batch, or shrink the step."""
        results = [t for t in history if t.gain is not None and t.values in self.batch]
        top = max(results, key=lambda t: t.gain, default=None)
        if top is not None and top.gain > self.best:
            self.best, self.center = top.gain, {**self.center, **top.values}
        else:
            self.frac /= 2

    def propose(self, space, history):
        if self.center is None:
            self.center = {n: p["_value"] for n, p in space.items()}
        while not self.queue:
            if self.batch:
                self._settle(history)
                self.batch = []
            if self.frac < self.min_frac or self.made >= self.max_trials:
                return None
            self.queue = self._neighbours(space)
            self.batch = list(self.queue)
            if not self.queue:
                return None
        self.made += 1
        return self.queue.pop(0)


class OptunaTPE:
    """Optuna's TPE sampler through its ask/tell interface (optional: pip install morphogen[optuna])."""
    name = "optuna"

    def __init__(self, trials: int = 20, seed: int | None = None):
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        self.optuna, self.trials, self.made, self.pending = optuna, trials, 0, {}
        self.study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))

    def propose(self, space, history):
        if self.made >= self.trials:
            return None
        self.made += 1
        t = self.study.ask()
        values = {}
        for n, p in sorted(space.items()):
            if p.get("choices") is not None:
                values[n] = t.suggest_categorical(n, list(p["choices"]))
            elif _is_int(p):
                values[n] = t.suggest_int(n, int(p["range"][0]), int(p["range"][1]))
            else:
                values[n] = t.suggest_float(n, float(p["range"][0]), float(p["range"][1]))
        self.pending[json.dumps(values, sort_keys=True)] = t
        return values

    def observe(self, trial: Trial) -> None:
        t = self.pending.pop(json.dumps(trial.values, sort_keys=True), None)
        if t is None:
            return
        if trial.gain is None:
            self.study.tell(t, state=self.optuna.trial.TrialState.FAIL)
        else:
            self.study.tell(t, trial.gain)


# --- the selector: an optimizer that chooses optimizers


class Bandit:
    """UCB1 over members on probe gains: try each once, then the one whose mean gain plus an
    exploration bonus is highest. A refused or failed proposal counts as a gain of `failure`.
    `prior` maps a member's name to (passes, verdicts) from earlier verdicts; its pass rate adds up
    to `prior_weight` to the member's score, a head start that probes soon outweigh."""
    name = "bandit"

    def __init__(self, c: float = 1.0, failure: float = -1.0, prior: dict[str, tuple[int, int]] | None = None,
                 prior_weight: float = 0.1):
        self.c, self.failure, self.prior, self.prior_weight = c, failure, prior or {}, prior_weight

    def choose(self, members: list[str], history: list[Trial]) -> str:
        gains = {m: [self.failure if t.gain is None else t.gain for t in history if t.optimizer == m] for m in members}
        untried = [m for m in members if not gains[m]]
        if untried:
            return max(untried, key=lambda m: self._head_start(m))  # ties keep the given order
        total = sum(len(g) for g in gains.values())

        def score(m):
            g = gains[m]
            return sum(g) / len(g) + self.c * math.sqrt(math.log(total) / len(g)) + self._head_start(m)
        return max(members, key=score)

    def _head_start(self, m: str) -> float:
        wins, n = self.prior.get(m, (0, 0))
        return self.prior_weight * wins / n if n else 0.0


class Selector:
    """An optimizer whose policy chooses which member proposes next. Members that run out are dropped;
    every member sees the whole history, so what one learns the others can use."""
    name = "selector"

    def __init__(self, members: list[Optimizer], policy=None, max_trials: int = 30):
        self.members = {m.name: m for m in members}
        self.policy, self.max_trials, self.made = policy or Bandit(), max_trials, 0
        self.proposer = ""

    def propose(self, space, history):
        while self.members and self.made < self.max_trials:
            name = self.policy.choose(list(self.members), history)
            values = self.members[name].propose(space, history)
            if values is None:
                del self.members[name]
                continue
            self.made += 1
            self.proposer = name
            return values
        return None

    def observe(self, trial: Trial) -> None:
        m = self.members.get(trial.optimizer)
        if m is not None and hasattr(m, "observe"):
            m.observe(trial)


def prior_from_evidence(evidence, target: str) -> dict[str, tuple[int, int]]:
    """(passes, verdicts) per optimizer label from earlier verdicts on this target."""
    out: dict[str, list[int]] = {}
    for r in evidence.dump():
        if r.get("kind") != "verdict" or (r.get("subject") or {}).get("path") != target:
            continue
        name = (r.get("labels") or {}).get("member") or (r.get("labels") or {}).get("optimizer")
        if name:
            w, n = out.setdefault(name, [0, 0])
            out[name] = [w + (r.get("verdict") == "pass"), n + 1]
    return {k: (v[0], v[1]) for k, v in out.items()}


# --- the catalog


@dataclass
class Entry:
    name: str
    kind: str                   # built-in | adapter | meta | planned | plugin
    description: str
    modalities: list[str]
    needs: list[str]
    factory: Callable[..., Optimizer] | None = None

    def available(self) -> bool:
        if self.factory is None:
            return False
        if self.name == "optuna":
            try:
                import optuna  # noqa: F401
            except ImportError:
                return False
        return True

    def describe(self) -> dict:
        return {"name": self.name, "kind": self.kind, "description": self.description,
                "modalities": self.modalities, "needs": self.needs, "available": self.available()}


def _selector(trials: int = 20, seed: int | None = None, steps: int = 5, members: list[str] | None = None,
              prior: dict | None = None, **_) -> Selector:
    names = members or [n for n in ("hillclimb", "random", "grid", "optuna") if CATALOG[n].available()]
    built = [make(n, trials=trials, seed=seed, steps=steps) for n in names]
    return Selector(built, Bandit(prior=prior), max_trials=trials)


CATALOG: dict[str, Entry] = {
    "grid": Entry("grid", "built-in", "every combination of choices, or evenly spaced values in each range",
                  ["numeric", "choices"], [], lambda steps=5, **_: Grid(steps=steps)),
    "random": Entry("random", "built-in", "values drawn at random within ranges and choices",
                    ["numeric", "choices"], [], lambda trials=20, seed=None, **_: RandomSearch(trials, seed)),
    "hillclimb": Entry("hillclimb", "built-in", "coordinate ascent from the base's values, halving the step",
                       ["numeric", "choices"], [], lambda trials=20, **_: HillClimb(max_trials=trials)),
    "optuna": Entry("optuna", "adapter", "Optuna's TPE sampler (ask/tell)", ["numeric", "choices"],
                    ["optuna (pip install morphogen[optuna])"],
                    lambda trials=20, seed=None, **_: OptunaTPE(trials, seed)),
    "selector": Entry("selector", "meta", "chooses which optimizer proposes next; policy: bandit "
                      "(UCB1 on probe gains, primed by earlier verdicts)", ["any its members take"], [], _selector),
    "gepa": Entry("gepa", "planned", "GEPA: reflective, Pareto-based evolution of anything interpretable as "
                  "text (prompts, code, configurations), using model calls; its adapters are modular",
                  ["text"], ["a text cell", "model calls", "the gepa package (MIT)"]),
    "selector-llm": Entry("selector-llm", "planned", "a selector policy that asks a model which optimizer to "
                          "try, with more context, and can search for and add catalog entries",
                          ["any"], ["model calls"]),
}


def _plugins() -> None:
    for ep in metadata.entry_points(group="morphogen.optimizers"):
        if ep.name not in CATALOG:
            try:
                CATALOG[ep.name] = Entry(ep.name, "plugin", f"from {ep.value}", ["?"], [], ep.load())
            except Exception as e:  # a broken plugin is listed, not fatal
                CATALOG[ep.name] = Entry(ep.name, "plugin", f"failed to load: {e}", ["?"], [])


_plugins()


def catalog() -> list[dict]:
    return [e.describe() for e in CATALOG.values()]


def make(name: str, **options) -> Optimizer:
    e = CATALOG.get(name)
    if e is None:
        raise LookupError(f"no optimizer {name!r}; the catalog has {', '.join(CATALOG)}")
    if not e.available():
        raise LookupError(f"optimizer {name!r} is {e.kind} and not available here: needs {', '.join(e.needs) or 'building'}")
    return e.factory(**options)


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


def space_of(spec: dict, tree_dir: Path, tree: Path | None = None, cfg: dict | None = None,
             cell: str | None = None) -> dict[str, dict]:
    """The agent-owned parameters with a range or choices: what an optimizer may search. With a cell,
    also those on the cells in its scope in the structure (read from `tree`, the base's checkout).
    Each entry carries `_value` (its value on the base) and `_dir` (where its file path starts)."""
    items = [(n, p, tree_dir) for n, p in (spec.get("parameters") or {}).items()]
    if cell and tree is not None:
        from .structure import Structure
        rel = Path((cfg or {}).get("structure", "cells.yaml"))
        s = Structure.load(tree / rel)
        if cell not in s.cells:
            raise judge_mod.JudgeError(f"no cell {cell!r} in the base's structure")
        items += [(f"{c}.{n}", p.model_dump(exclude_none=True), (tree / rel).parent)
                  for c in sorted(s.scope(cell)) for n, p in s.cells[c].parameters.items()]
    out, seen = {}, set()
    for n, p, d in items:
        where = (str((d / p["file"]).resolve()), p.get("name"), p.get("key"))
        if where in seen:
            continue
        seen.add(where)
        if p.get("owner") == "agent" and (p.get("range") is not None or p.get("choices") is not None):
            out[n] = {**p, "_value": judge_mod._read_parameter(d, p), "_dir": d}
    return out


def tune(root: Path, cfg: dict, target: str, optimizer: Optimizer, evidence, base: str = "main",
         rounds: int = 2, max_trials: int = 50, cell: str | None = None) -> dict:
    """Search the target's agent-owned parameters with `optimizer`; probe every proposal; judge the best."""
    repo = judge_mod.repo_root(root)
    rel = (Path(root) / target).resolve().relative_to(repo)
    base_sha = judge_mod.resolve(repo, base)
    trials: list[Trial] = []
    seen: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="morphogen-tune-") as tmp:
        work = Path(tmp) / "w"
        _git(repo, "worktree", "add", "--detach", "--quiet", str(work), base_sha)
        try:
            spec = judge_mod.load_spec(work, rel)
            space = space_of(spec, work / rel, work, cfg, cell)
            if not space:
                raise judge_mod.JudgeError("no agent-owned parameters with a range or choices in target.yaml")
            metrics = judge_mod._check_spec(spec)
            primary = next(k for k, v in metrics.items() if v.get("primary"))
            attempts = 0
            while len(trials) < max_trials and attempts < 4 * max_trials:
                attempts += 1
                values = optimizer.propose({k: {x: y for x, y in v.items() if x != "_dir"} for k, v in space.items()},
                                           trials)
                if values is None:
                    break
                who = getattr(optimizer, "proposer", "") or optimizer.name
                key = json.dumps(values, sort_keys=True)
                if key in seen or all(values.get(k) == space[k]["_value"] for k in values):
                    # Already tried, or the base's own values: report the known result, try nothing new.
                    old = next((t for t in trials if t.values == values), None)
                    known = Trial(values, old.branch if old else "", old.gain if old else 0.0, who)
                    if hasattr(optimizer, "observe"):
                        optimizer.observe(known)
                    continue
                seen.add(key)
                _git(work, "checkout", "--quiet", "--detach", base_sha)
                for k, v in values.items():
                    write_parameter(space[k]["_dir"], space[k], v)
                branch = f"morphogen/tune/{rel.name}/{optimizer.name}-{len(trials) + 1}"
                _git(work, "checkout", "--quiet", "-B", branch)
                _git(work, "commit", "--quiet", "-am", f"tune {rel.name} ({who}): " +
                     ", ".join(f"{k}={v!r}" for k, v in values.items()))
                pr = judge_mod.probe(repo, cfg, str(rel), branch, evidence, base=base_sha, cases=1, rounds=rounds,
                                     cell=cell)
                gain = None if pr.get("forbidden") or pr.get("parameter_violations") or \
                    not (pr.get("check") or {"passed": True}).get("passed", True) or \
                    not all(x["passed"] for x in pr.get("interfaces", [])) \
                    else (pr.get("metrics") or {}).get(primary, {}).get("gain")
                trial = Trial(values, branch, gain, who, pr)
                trials.append(trial)
                if hasattr(optimizer, "observe"):
                    optimizer.observe(trial)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(work)], cwd=repo, capture_output=True)
    scored = [t for t in trials if t.gain is not None]
    best = max(scored, key=lambda t: t.gain, default=None)
    out = {"target": str(rel), "optimizer": optimizer.name, "primary": primary,
           "trials": [{"values": t.values, "branch": t.branch, "probe_gain": t.gain, "optimizer": t.optimizer}
                      for t in trials]}
    if best is None or best.gain <= 0:
        out["verdict"] = None
        out["note"] = "no proposal improved on the base in probes; nothing sent to the judge"
        return out
    labels = {"optimizer": optimizer.name, "values": json.dumps(best.values, sort_keys=True)}
    if best.optimizer and best.optimizer != optimizer.name:
        labels["member"] = best.optimizer
    v = judge_mod.judge(repo, cfg, str(rel), base_sha, best.branch, evidence, labels, cell=cell)
    out.update({"best": {"values": best.values, "branch": best.branch, "probe_gain": best.gain,
                         "optimizer": best.optimizer}, "verdict": v["verdict"], "judge": v})
    return out


# Backwards-compatible name: the built-in optimizers by name.
OPTIMIZERS = {"grid": Grid, "random": RandomSearch, "hillclimb": HillClimb}
