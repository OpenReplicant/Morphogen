"""The optimizer slot: a catalog of optimizers behind one interface, and `tune`.

An optimizer proposes values for a cell's bounded settings; Morphogen writes each proposal
onto a branch, scores it with a probe (the cheap inner evaluator: practice, never a verdict), tells
the optimizer the result, and sends only the best proposal to the judge, which scores it on the
held-out cases with full statistics.

The catalog (`CATALOG`, `catalog()`):

- built in, standard library only: `grid`, `random`, `hillclimb`;
- built in, for leaving a local optimum: `hillclimb` with `restarts`, and `anneal`;
- adapters to other libraries, available when installed: `optuna` (TPE sampling) and `gepa`
  (reflective evolution of text cells, with a model proposing: by default `claude -p --model sonnet`);
- meta: `selector`, an optimizer whose policy chooses which member proposes next. Its first policy
  is `bandit` (UCB1 on probe gains, optionally primed by earlier verdicts): a fast, system-1 rule.
  A policy is anything with `choose(members, history) -> name`;
- planned, not built: an `llm` selector policy, which could also search for and add optimizers to
  the catalog.

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
    refused: str = ""            # why tune refused the proposal before writing anything
    diagnostics: dict = field(repr=False, default_factory=dict)   # what the probe found, for learners


class Optimizer(Protocol):
    """The contract. An optimizer is given a space: each entry is a setting's declaration plus
    `_kind` (number, choice or text), `_value` (its value on the base) and, for text, `file`. It sees
    only the kinds it declares in `kinds` (default number and choice). It never holds the evaluator:
    each proposal is written, committed and probed by tune, and only the best goes to the judge.

    Two styles:
    - ask/tell: `propose(space, history) -> values | None`, and optionally `observe(trial)`;
    - driver: `search(space, evaluate, budget)`, calling `evaluate(values) -> Trial` itself (GEPA).
    """
    name: str

    def propose(self, space: dict[str, dict], history: list[Trial]) -> dict[str, Any] | None: ...


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


def _random_point(space, rng: random.Random) -> dict:
    out = {}
    for n, p in sorted(space.items()):
        if p.get("choices") is not None:
            out[n] = rng.choice(list(p["choices"]))
        else:
            lo, hi = p["range"]
            out[n] = rng.randint(int(lo), int(hi)) if _is_int(p) else rng.uniform(lo, hi)
    return out


class HillClimb:
    """Coordinate ascent from the base's values: step each parameter up and down, move to the best
    improvement, and halve the step when nothing improves, until the step is below `min_step` of the
    range. Choices step to the neighbouring choice. With `restarts`, a climb that has converged
    starts again from a random point, so one low peak near the base does not end the search."""
    name = "hillclimb"

    def __init__(self, start_step: float = 0.25, min_step: float = 0.02, max_trials: int = 60,
                 restarts: int = 0, seed: int | None = None):
        self.frac, self.min_frac, self.max_trials = start_step, min_step, max_trials
        self.start_frac, self.restarts, self.rng, self.restarting = start_step, restarts, random.Random(seed), None
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
        """Move to the best result of the last batch, or shrink the step. After a restart, the new
        start is the centre whatever it scored: the climb is local from there."""
        if self.restarting is not None:
            got = [t.gain for t in history if t.values == self.restarting and t.gain is not None]
            self.center, self.best = {**self.center, **self.restarting}, (got[-1] if got else -math.inf)
            self.restarting = None
            return
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
            if self.made >= self.max_trials:
                return None
            if self.frac < self.min_frac:
                if self.restarts <= 0:
                    return None
                self.restarts -= 1
                self.frac = self.start_frac
                self.restarting = _random_point(space, self.rng)
                self.queue, self.batch = [self.restarting], [self.restarting]
                break
            self.queue = self._neighbours(space)
            self.batch = list(self.queue)
            if not self.queue:
                return None
        self.made += 1
        return self.queue.pop(0)


class Anneal:
    """Simulated annealing from the base's values: propose a random neighbour (one setting moved by a
    step that shrinks with the temperature, or a random choice); accept it if it is better, or if it
    is worse with probability exp(delta / temperature), so early on the search can leave a low peak.
    The temperature falls geometrically from `t0` to `t1` over `trials`."""
    name = "anneal"

    def __init__(self, trials: int = 40, seed: int | None = None, t0: float = 0.3, t1: float = 0.005):
        self.trials, self.rng, self.made = trials, random.Random(seed), 0
        self.t0, self.cool = t0, (t1 / t0) ** (1 / max(1, trials - 1))
        self.current: dict | None = None
        self.gain, self.last = 0.0, None   # the base scores 0

    def _temp(self) -> float:
        return self.t0 * self.cool ** self.made

    def propose(self, space, history):
        if self.made >= self.trials:
            return None
        if self.current is None:
            self.current = {n: p["_value"] for n, p in space.items()}
        n = self.rng.choice(sorted(space))
        p, v = space[n], self.current[n]
        if p.get("choices") is not None:
            new = self.rng.choice([c for c in p["choices"] if c != v] or list(p["choices"]))
        else:
            lo, hi = p["range"]
            width = (hi - lo) * max(self._temp() / self.t0, 0.05)
            new = min(hi, max(lo, v + self.rng.gauss(0, width)))
            new = round(new) if _is_int(p) else new
        self.made += 1
        self.last = {**self.current, n: new}
        return self.last

    def observe(self, trial: Trial) -> None:
        if trial.values != self.last or trial.gain is None:
            return
        delta, temp = trial.gain - self.gain, max(self._temp(), 1e-9)
        if delta >= 0 or self.rng.random() < math.exp(delta / temp):
            self.current, self.gain = dict(trial.values), trial.gain


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


# --- GEPA: reflective evolution of text cells, with a model proposing each new text


class ClaudeCLI:
    """A language model for GEPA's reflection, through the Claude Code CLI on the operator's own
    subscription: `claude -p --model sonnet`, with no tools, no MCP servers and no saved session, run
    in an empty directory, so the proposer can only answer, never act. `prompt -> text`."""

    SYSTEM = ("You improve one piece of text in someone's system. You have no tools and cannot run or read "
              "anything: answer from the prompt alone, and put the complete new text in one fenced code block.")

    def __init__(self, model: str = "sonnet", timeout: int = 300, command: str = "claude"):
        self.model, self.timeout, self.command = model, timeout, command
        self.total_cost, self.calls = 0.0, 0

    def __call__(self, prompt: str | list[dict]) -> str:
        if not isinstance(prompt, str):
            prompt = "\n\n".join(m.get("content", "") if isinstance(m.get("content"), str) else
                                   json.dumps(m.get("content")) for m in prompt)
        with tempfile.TemporaryDirectory(prefix="morphogen-lm-") as d:
            r = subprocess.run([self.command, "-p", "--model", self.model, "--tools", "", "--strict-mcp-config",
                                "--no-session-persistence", "--output-format", "json", "--system-prompt", self.SYSTEM],
                               input=prompt, cwd=d, capture_output=True, text=True, timeout=self.timeout)
        if r.returncode != 0:
            raise RuntimeError(f"{self.command} -p failed ({r.returncode}): {(r.stderr or r.stdout)[-400:]}")
        out = json.loads(r.stdout)
        self.calls += 1
        self.total_cost += float(out.get("total_cost_usd") or 0.0)
        if out.get("is_error"):
            raise RuntimeError(f"{self.command} -p: {out.get('result')}")
        return out.get("result") or ""


class Gepa:
    """GEPA's optimize_anything over the cell's text (whole files its `change` names): a driver. GEPA
    asks for each candidate's score through tune's evaluate (a probe it cannot see inside), and the
    probe's diagnostics (failing tests, per-case misses, metrics) are its side information for
    reflection. Only the best candidate goes to the judge, as for every optimizer.

    The model GEPA reflects with is `lm` (any `prompt -> text` callable), by default ClaudeCLI with
    sonnet. Optional: pip install morphogen[gepa] (gepa 0.1.4, MIT)."""
    name = "gepa"
    kinds = {"text"}

    def __init__(self, trials: int = 20, seed: int | None = None, lm=None, model: str = "sonnet",
                 objective: str | None = None):
        self.trials, self.seed, self.lm = trials, seed or 0, lm or ClaudeCLI(model)
        self.objective = objective

    def search(self, space: dict[str, dict], evaluate, budget: int) -> None:
        import gepa.optimize_anything as oa
        seed = {k: v["_value"] for k, v in space.items()}

        def evaluator(candidate):
            t = evaluate(dict(candidate), self.name)
            info = {"gain": t.gain, **t.diagnostics}
            if t.refused:
                info["refused"] = t.refused
            return (t.gain if t.gain is not None else -1.0), info

        files = ", ".join(v["file"] for v in space.values())
        config = oa.GEPAConfig(
            engine=oa.EngineConfig(max_metric_calls=min(self.trials, budget) + 1, seed=self.seed, parallel=False,
                                   use_cloudpickle=False, raise_on_exception=True),
            reflection=oa.ReflectionConfig(reflection_lm=self.lm),
            tracking=oa.TrackingConfig())
        oa.optimize_anything(
            seed, evaluator=evaluator, config=config,
            objective=self.objective or "Raise the score: the gain over the original on the cell's primary metric.",
            background=(f"Each parameter is the whole text of one file ({files}). Every candidate is run and scored "
                        "outside your view; its tests and its neighbours' contract tests must still pass, or it "
                        "scores -1 with the reason given. Nothing else in the project can be changed."))


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
    every member sees the whole history, so what one learns the others can use. The stagnation
    signal: after `patience` trials without a new best, the member used least recently proposes next,
    whatever the policy prefers, so one member stuck on a local peak cannot hold the search."""
    name = "selector"

    def __init__(self, members: list[Optimizer], policy=None, max_trials: int = 30, patience: int = 0):
        self.members = {m.name: m for m in members}
        self.policy, self.max_trials, self.made = policy or Bandit(), max_trials, 0
        self.patience, self.proposer = patience, ""
        self.kinds = set().union(*(_kinds(m) for m in members)) if members else {"number", "choice"}

    def _stagnant(self, history) -> bool:
        if not self.patience or len(history) < self.patience:
            return False
        gains = [t.gain if t.gain is not None else -math.inf for t in history]
        best_before = max(gains[:-self.patience], default=0.0)
        return max(gains[-self.patience:]) <= max(best_before, 0.0)

    def propose(self, space, history):
        while self.members and self.made < self.max_trials:
            names = list(self.members)
            if self._stagnant(history) and len(names) > 1:
                last = {t.optimizer: i for i, t in enumerate(history)}
                name = min(names, key=lambda m: last.get(m, -1))
            else:
                name = self.policy.choose(names, history)
            member = self.members[name]
            mine = {k: v for k, v in space.items() if v.get("_kind", "number") in _kinds(member)}
            values = member.propose(mine, history) if mine else None
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
        module = {"optuna": "optuna", "gepa": "gepa"}.get(self.name)
        if module:
            try:
                __import__(module)
            except ImportError:
                return False
        return True

    def describe(self) -> dict:
        return {"name": self.name, "kind": self.kind, "description": self.description,
                "modalities": self.modalities, "needs": self.needs, "available": self.available()}


def _selector(trials: int = 20, seed: int | None = None, steps: int = 5, members: list[str] | None = None,
              prior: dict | None = None, patience: int = 5, **_) -> Selector:
    names = members or [n for n in ("hillclimb", "anneal", "random", "grid", "optuna") if CATALOG[n].available()]
    built = [make(n, trials=trials, seed=seed, steps=steps) for n in names]
    return Selector(built, Bandit(prior=prior), max_trials=trials, patience=patience)


CATALOG: dict[str, Entry] = {
    "grid": Entry("grid", "built-in", "every combination of choices, or evenly spaced values in each range",
                  ["numeric", "choices"], [], lambda steps=5, **_: Grid(steps=steps)),
    "random": Entry("random", "built-in", "values drawn at random within ranges and choices",
                    ["numeric", "choices"], [], lambda trials=20, seed=None, **_: RandomSearch(trials, seed)),
    "hillclimb": Entry("hillclimb", "built-in", "coordinate ascent from the base's values, halving the step; "
                       "`restarts` climbs again from random points", ["numeric", "choices"], [],
                       lambda trials=20, restarts=0, seed=None, **_: HillClimb(max_trials=trials, restarts=restarts,
                                                                               seed=seed)),
    "anneal": Entry("anneal", "built-in", "simulated annealing from the base's values: accepts some worse "
                    "moves early, so it can leave a low peak", ["numeric", "choices"], [],
                    lambda trials=20, seed=None, **_: Anneal(trials, seed)),
    "optuna": Entry("optuna", "adapter", "Optuna's TPE sampler (ask/tell)", ["numeric", "choices"],
                    ["optuna (pip install morphogen[optuna])"],
                    lambda trials=20, seed=None, **_: OptunaTPE(trials, seed)),
    "selector": Entry("selector", "meta", "chooses which optimizer proposes next; policy: bandit "
                      "(UCB1 on probe gains, primed by earlier verdicts); after `patience` trials without a new "
                      "best, the least recently used member goes next", ["any its members take"], [], _selector),
    "gepa": Entry("gepa", "adapter", "GEPA's optimize_anything: reflective, Pareto-based evolution of text "
                  "(whole files a cell may change: prompts, skills, code), with probe diagnostics as feedback",
                  ["text"], ["gepa (pip install morphogen[gepa])", "a model: the claude CLI (sonnet) by default"],
                  lambda trials=20, seed=None, lm=None, model="sonnet", **_: Gepa(trials, seed, lm, model)),
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


GLOB = re.compile(r"[*?\[]")


def space_of(tree: Path, cell: str) -> dict[str, dict]:
    """What an optimizer may search in `cell`'s scope, in the project on `tree` (the base's checkout):
    each bounded setting (`_kind` number or choice, named `cell.NAME`), and each whole file a cell's
    `change` names by its path (`_kind` text, named `cell.path`), with its content on the base."""
    proj = judge_mod.structure_of(tree)
    s = proj.structure()
    out = {}
    for c in sorted(s.scope(cell)):
        for n, p in s.cells[c].parameters.items():
            d = p.model_dump(exclude_none=True)
            if d.get("owner") == "agent" and (d.get("range") is not None or d.get("choices") is not None):
                kind = "choice" if d.get("choices") is not None else "number"
                out[f"{c}.{n}"] = {**d, "_kind": kind, "_value": judge_mod._read_parameter(tree, d), "_dir": tree}
        for e in proj.changes.get(c, []):
            path = e["path"]
            if "name" in e or "key" in e or GLOB.search(path) or path.endswith("/") or not (tree / path).is_file():
                continue
            try:
                text = (tree / path).read_text()
            except (OSError, UnicodeDecodeError):
                continue
            out[f"{c}.{path}"] = {"file": path, "_kind": "text", "_value": text, "_dir": tree}
    return out


def _kinds(optimizer) -> set[str]:
    return set(getattr(optimizer, "kinds", None) or {"number", "choice"})


def check_proposal(space: dict[str, dict], values: Any) -> str:
    """Why `values` is not a proposal within `space`, or "" when it is."""
    if not isinstance(values, dict) or not values:
        return "a proposal is a non-empty mapping of names in the space to values"
    for k, v in values.items():
        p = space.get(k)
        if p is None:
            return f"{k!r} is outside the space it was given"
        if p["_kind"] == "text":
            if not isinstance(v, str):
                return f"{k} is text, not {type(v).__name__}"
        elif p["_kind"] == "choice":
            if v not in p["choices"]:
                return f"{k}={v!r} is not one of {p['choices']}"
        elif isinstance(v, bool) or not isinstance(v, (int, float)) or not (p["range"][0] <= v <= p["range"][1]):
            return f"{k}={v!r} is outside its range {list(p['range'])}"
    return ""


def diagnostics(pr: dict) -> dict:
    """What a probe found, in a form a learning optimizer can read (GEPA's side information)."""
    out: dict = {}
    for k in ("forbidden", "parameter_violations"):
        if pr.get(k):
            out[k] = pr[k]
    if pr.get("check") and not pr["check"].get("passed", True):
        out["tests_failed"] = pr["check"].get("output", "")
    bad = [x for x in pr.get("interfaces", []) if not x["passed"]]
    if bad:
        out["interface_tests_failed"] = [{"interface": x["interface"], "output": x.get("output", "")} for x in bad]
    wrong = [c for c in pr.get("cases", []) if c["status"] != "ok"]
    if wrong:
        out["generated_cases_wrong"] = wrong[:5]
    if pr.get("metrics"):
        out["metrics"] = pr["metrics"]
    if pr.get("timed_output_mismatches"):
        out["timed_output_mismatches"] = pr["timed_output_mismatches"]
    if pr.get("observer_error"):
        out["observer_error"] = pr["observer_error"]
    return out


def tune(root: Path, cfg: dict, target: str, optimizer: Optimizer, evidence, base: str = "main",
         rounds: int = 2, max_trials: int = 50, cell: str | None = None) -> dict:
    """Search the cell's space with `optimizer`; probe every proposal; judge the best."""
    repo = judge_mod.repo_root(root)
    base_sha = judge_mod.resolve(repo, base)
    trials: list[Trial] = []
    known: dict[str, Trial] = {}
    primary = ""
    with tempfile.TemporaryDirectory(prefix="morphogen-tune-") as tmp:
        work = Path(tmp) / "w"
        _git(repo, "worktree", "add", "--detach", "--quiet", str(work), base_sha)
        try:
            spec, rel, cell, _ = judge_mod._target(root, repo, cfg, target, work, cell)
            label, subject = cell, f"cell:{cell}"
            full = space_of(work, cell)
            kinds = _kinds(optimizer)
            space = {k: v for k, v in full.items() if v["_kind"] in kinds}
            if not space:
                raise judge_mod.JudgeError(f"nothing in {subject}'s `change` that {optimizer.name} can search "
                                           f"(it takes {', '.join(sorted(kinds))})")
            metrics = judge_mod._check_spec(spec)
            primary = next(k for k, v in metrics.items() if v.get("primary"))
            view = {k: {x: y for x, y in v.items() if x != "_dir"} for k, v in space.items()}
            driver = hasattr(optimizer, "search")

            def evaluate(values: dict, who: str | None = None) -> Trial:
                """Write `values` on a branch from the base, probe it, and record the trial."""
                who = who or getattr(optimizer, "proposer", "") or optimizer.name
                why = check_proposal(space, values)
                if why:
                    trial = Trial(values if isinstance(values, dict) else {}, "", None, who, refused=why,
                                  diagnostics={"refused": why})
                    trials.append(trial)
                    return trial
                key = json.dumps(values, sort_keys=True)
                if key in known:
                    return Trial(values, known[key].branch, known[key].gain, who, diagnostics=known[key].diagnostics)
                if all(values[k] == space[k]["_value"] for k in values):
                    # The base's own values: no gain, nothing to try. A driver (GEPA) learns from the
                    # feedback, so the base is probed once for it, outside the trial budget.
                    if driver and "base" not in known:
                        _git(work, "checkout", "--quiet", "--detach", base_sha)
                        _git(work, "checkout", "--quiet", "-B", f"morphogen/tune/{_slug(label)}/base")
                        _git(work, "commit", "--quiet", "--allow-empty", "-m", "the base, for feedback")
                        pr = judge_mod.probe(repo, cfg, subject, f"morphogen/tune/{_slug(label)}/base", evidence,
                                             base=base_sha, cases=1, rounds=rounds, cell=cell)
                        known["base"] = Trial(values, "", 0.0, who, pr, diagnostics=diagnostics(pr))
                    d = known["base"].diagnostics if "base" in known else {}
                    return Trial(values, "", 0.0, who, diagnostics=d)
                if len([x for x in trials if x.branch]) >= max_trials:
                    return Trial(values, "", None, who, refused="the trial budget is spent")
                _git(work, "checkout", "--quiet", "--detach", base_sha)
                for k, v in values.items():
                    if space[k]["_kind"] == "text":
                        (work / space[k]["file"]).write_text(v)
                    else:
                        write_parameter(space[k]["_dir"], space[k], v)
                branch = f"morphogen/tune/{_slug(label)}/{optimizer.name}-{len(trials) + 1}"
                _git(work, "checkout", "--quiet", "-B", branch)
                _git(work, "commit", "--quiet", "--allow-empty", "-am", f"tune {label} ({who}): " +
                     ", ".join(f"{k}={_short(v)}" for k, v in values.items()))
                pr = judge_mod.probe(repo, cfg, subject, branch, evidence, base=base_sha, cases=1, rounds=rounds,
                                     cell=cell)
                gain = None if pr.get("forbidden") or pr.get("parameter_violations") or \
                    not (pr.get("check") or {"passed": True}).get("passed", True) or \
                    not all(x["passed"] for x in pr.get("interfaces", [])) \
                    else (pr.get("metrics") or {}).get(primary, {}).get("gain")
                trial = Trial(values, branch, gain, who, pr, diagnostics=diagnostics(pr))
                trials.append(trial)
                known[key] = trial
                return trial

            if hasattr(optimizer, "search"):
                if getattr(optimizer, "objective", "") is None and spec.get("description"):
                    optimizer.objective = spec["description"]   # the operator's statement of intent
                optimizer.search(view, evaluate, max_trials)
            else:
                attempts = 0
                while len([x for x in trials if x.branch]) < max_trials and attempts < 4 * max_trials:
                    attempts += 1
                    values = optimizer.propose(view, trials)
                    if values is None:
                        break
                    trial = evaluate(values)
                    if hasattr(optimizer, "observe"):
                        optimizer.observe(trial)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(work)], cwd=repo, capture_output=True)
    scored = [t for t in trials if t.gain is not None and t.branch]
    best = max(scored, key=lambda t: t.gain, default=None)
    out = {"target": subject, "optimizer": optimizer.name, "primary": primary,
           "trials": [{"values": {k: _short(v) for k, v in t.values.items()}, "branch": t.branch,
                       "probe_gain": t.gain, "optimizer": t.optimizer, **({"refused": t.refused} if t.refused else {})}
                      for t in trials]}
    if best is None or best.gain <= 0:
        out["verdict"] = None
        out["note"] = "no proposal improved on the base in probes; nothing sent to the judge"
        return out
    labels = {"optimizer": optimizer.name, "values": json.dumps({k: _short(v) for k, v in best.values.items()},
                                                                sort_keys=True)}
    if best.optimizer and best.optimizer != optimizer.name:
        labels["member"] = best.optimizer
    v = judge_mod.judge(repo, cfg, subject, base_sha, best.branch, evidence, labels, cell=cell)
    out.update({"best": {"values": best.values, "branch": best.branch, "probe_gain": best.gain,
                         "optimizer": best.optimizer}, "verdict": v["verdict"], "judge": v})
    return out


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-") or "cell"


def _short(v: Any, n: int = 80) -> Any:
    """Values as recorded: text is cut to `n` characters, everything else is kept."""
    return v if not isinstance(v, str) or len(v) <= n else v[:n] + f"... ({len(v)} characters)"


# Backwards-compatible name: the built-in optimizers by name.
OPTIMIZERS = {"grid": Grid, "random": RandomSearch, "hillclimb": HillClimb}
