"""The judge: score a candidate commit against a base commit, by the base's rules.

What makes it hard to fool:

- The target's spec (`target.yaml`) and harness files (benchmark, tests,
  input generator) come from the base commit and are laid over the
  candidate, so a candidate cannot change how it is scored.
- Time and memory are measured from outside the measured process, by a
  wrapper that waits for it and reads the operating system's resource usage.
  Numbers the measured code prints are recorded as "reported" and can never
  decide the verdict.
- Inputs come from a fresh random seed every round: nothing to read in
  advance, and nothing one round learns helps the next. Base and candidate
  share the seed within a round. Without a container, each run of the code
  under test also gets its own empty TMPDIR and HOME.
- A candidate may not add or change files that shadow standard-library
  modules, customise the interpreter (`json.py`, `sitecustomize.py`, `.pth`),
  or shadow a harness module (a `gen/` package or `gen.so` beside `gen.py`).
- Every timed run must print what the base prints on the same input, so code
  cannot do less work only when it is being timed.
- Runs are paired and alternate order between rounds (ABBA) after a warm-up.
  A gain counts only if the median paired gain (or the mean, for scores that
  often tie) clears the bar and a sign test says the candidate wins more
  untied pairs than luck explains (p <= 0.01); close calls get more rounds,
  up to a limit.
- Quality is scored outside the candidate: a scorer from the base commit reads each timed run's
  output in its own process, with held-out answers kept outside the repository and given only to
  it, so a candidate can neither print its own score nor read the answers.
- Every verdict is written to the evidence log as `trust: measured, by: judge`.
"""

from __future__ import annotations

import ast
import datetime
import json
import math
import random
import secrets
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import tomllib
from contextlib import contextmanager
from pathlib import Path

import yaml


from . import documents
from .runner import capabilities, missing, run, sandbox_mode
from .structure import Structure

INTERFACES = ("direct", "simulated")
JUDGE_METRICS = ("wall_seconds", "cpu_seconds", "max_rss_kb")
MARK = "__MORPHOGEN_JUDGE__"
FORBIDDEN_MODULES = set(sys.stdlib_module_names) | {"sitecustomize", "usercustomize"}

# Runs the measured command as a child process and reports its resource usage.
# It runs in its own process, so code under test cannot patch it.
WRAPPER = r"""
import json, os, subprocess, sys, tempfile, time
o, e = tempfile.TemporaryFile(), tempfile.TemporaryFile()
t0 = time.perf_counter()
p = subprocess.Popen(sys.argv[1], shell=True, stdout=o, stderr=e)
_, status, ru = os.wait4(p.pid, 0)
wall = time.perf_counter() - t0
p.returncode = os.waitstatus_to_exitcode(status)
o.seek(0); e.seek(0)
sys.stdout.write(o.read().decode(errors="replace")); sys.stderr.write(e.read().decode(errors="replace"))
sys.stdout.write("\n__MORPHOGEN_JUDGE__" + json.dumps({"rc": p.returncode, "wall_seconds": wall,
    "cpu_seconds": ru.ru_utime + ru.ru_stime, "max_rss_kb": ru.ru_maxrss}) + "\n")
"""


class JudgeError(Exception):
    pass


def _git(cwd: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise JudgeError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout.strip()


def repo_root(root: Path) -> Path:
    return Path(_git(root, "rev-parse", "--show-toplevel")).resolve()


def resolve(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")


@contextmanager
def worktrees(repo: Path, shas: list[str]):
    tmp = Path(tempfile.mkdtemp(prefix="morphogen-judge-"))
    paths = []
    try:
        for i, sha in enumerate(shas):
            p = tmp / f"t{i}"
            _git(repo, "worktree", "add", "--detach", "--quiet", str(p), sha)
            paths.append(p)
        yield paths
    finally:
        for p in paths:
            subprocess.run(["git", "worktree", "remove", "--force", str(p)], cwd=repo, capture_output=True)
        subprocess.run(["git", "worktree", "prune"], cwd=repo, capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


def load_spec(tree: Path, rel: Path) -> dict:
    f = tree / rel / "target.yaml"
    if not f.exists():
        raise JudgeError(f"no target.yaml at {rel} on the base commit")
    try:
        return documents.load("target", f)
    except documents.DocumentError as e:
        raise JudgeError(f"target.yaml on the base commit: {'; '.join(e.problems)}") from None


def _target_name(spec: dict, rel: Path) -> str:
    return spec.get("name") or rel.name


def _interface(spec: dict) -> tuple[str, str]:
    """`direct`: the judge acts on the real system. `simulated`: on a model of it.

    Returns the interface and the trust level its verdicts get. A verdict on a
    simulator is evidence about the model, not about reality.
    """
    interface = spec.get("interface", "direct")
    if interface not in INTERFACES:
        raise JudgeError(f"target.yaml interface must be one of {', '.join(INTERFACES)}, not {interface!r}")
    if interface == "simulated" and not spec.get("simulates"):
        raise JudgeError("a simulated target must say what it simulates (simulates: ...)")
    return interface, ("measured" if interface == "direct" else "simulated")


SIMULATED_NOTE = ("this verdict is about a simulator ({what}), not reality; applying the change to the real "
                  "system needs a direct trial or the operator's explicit approval")


def _read_parameter(tree_dir: Path, p: dict):
    """A parameter's value in one tree, read statically: a module-level constant in a Python file (the
    last assignment wins), or a dotted key in a YAML, JSON or TOML file. LookupError if it is not there."""
    f = tree_dir / p["file"]
    if not f.is_file():
        raise LookupError(f"{p['file']} is missing")
    text = f.read_text()
    if p.get("name"):
        value, found = None, False
        for node in ast.parse(text).body:
            if isinstance(node, ast.Assign):
                targets, v = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, v = [node.target], node.value
            else:
                continue
            if any(isinstance(t, ast.Name) and t.id == p["name"] for t in targets):
                try:
                    value, found = ast.literal_eval(v), True
                except ValueError:
                    raise LookupError(f"{p['name']} in {p['file']} is not a literal") from None
        if not found:
            raise LookupError(f"no module-level {p['name']} in {p['file']}")
        return json.loads(json.dumps(value, default=str))
    data = tomllib.loads(text) if f.suffix == ".toml" else yaml.safe_load(text)
    for part in p["key"].split("."):
        if not isinstance(data, dict) or part not in data:
            raise LookupError(f"no key {p['key']} in {p['file']}")
        data = data[part]
    return data


def _parameters(spec: dict, bdir: Path, cdir: Path) -> tuple[dict, list[str]]:
    """The target's declared parameters, read in the base and the candidate (after the overlay), and the
    changes the candidate may not make: to a judge- or operator-owned parameter, an agent-owned one outside
    its range or choices, or one that can no longer be read."""
    values, violations = {}, []
    for name, p in (spec.get("parameters") or {}).items():
        try:
            b = _read_parameter(bdir, p)
        except (LookupError, SyntaxError) as e:
            raise JudgeError(f"parameter {name} cannot be read on the base: {e}") from None
        try:
            c = _read_parameter(cdir, p)
        except (LookupError, SyntaxError) as e:
            values[name] = {"owner": p["owner"], "base": b, "candidate": None}
            violations.append(f"the parameter {name} can no longer be read ({e})")
            continue
        values[name] = {"owner": p["owner"], "base": b, "candidate": c}
        if c == b:
            continue
        if p["owner"] != "agent":
            violations.append(f"changes the {p['owner']}-owned parameter {name} ({b!r} -> {c!r})")
        elif p.get("range") and not (isinstance(c, (int, float)) and p["range"][0] <= c <= p["range"][1]):
            violations.append(f"sets {name} to {c!r}, outside its range {p['range']}")
        elif p.get("choices") and c not in p["choices"]:
            violations.append(f"sets {name} to {c!r}, not one of {p['choices']}")
    return values, violations


def _overlay(spec: dict, base_dir: Path, cand_dir: Path) -> None:
    """Copy the base's harness files over the candidate's."""
    for name in list(spec.get("harness", [])) + ["target.yaml"]:
        src, dst = base_dir / name, cand_dir / name
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        elif dst.exists():
            dst.unlink()


def _changed(repo: Path, base: str, cand: str, rel: Path) -> list[str]:
    out = _git(repo, "diff", "--name-only", "--no-renames", base, cand, "--", str(rel))
    return [line for line in out.splitlines() if line]


def _import_name(filename: str) -> str:
    """The module name a file or directory would be imported as: gen.py, gen.cpython-312.so, gen/ -> gen."""
    return filename.split(".", 1)[0]


def _forbidden(changed: list[str], rel: Path, harness: list[str] = ()) -> list[str]:
    """Changed paths that shadow a standard module, customise the interpreter, or shadow a harness
    module (a package `gen/` or `gen.so` beside the harness's `gen.py` would be imported instead)."""
    harness_mods = {(Path(h).parent, _import_name(Path(h).name)) for h in harness if h.endswith(".py")}
    harness_files = {Path(h) for h in harness} | {Path("target.yaml")}
    bad = []
    for path in changed:
        local = Path(path).relative_to(rel)
        parts = local.parts
        top = parts[0]
        name = top[:-3] if top.endswith(".py") else top
        if top.endswith(".pth") or (name in FORBIDDEN_MODULES and (top.endswith(".py") or len(parts) > 1)):
            bad.append(path)
            continue
        if local in harness_files:
            continue  # replaced by the base's copy
        # Any prefix of the path may be a package or module beside a harness module of that name.
        for depth in range(1, len(parts) + 1):
            if (Path(*parts[:depth - 1]), _import_name(parts[depth - 1])) in harness_mods:
                bad.append(path)
                break
    return bad


def _timed(cmd: str, cwd: Path, cfg: dict, env: dict, timeout: int) -> tuple[dict, str]:
    full = f"python3 -c {shlex.quote(WRAPPER)} {shlex.quote(cmd)}"
    r = run(full, cwd, cfg, env=env, timeout=timeout, private=True)
    lines = r.out.rstrip("\n").splitlines()
    if r.rc != 0 or not lines or not lines[-1].startswith(MARK):
        raise JudgeError(f"the measuring wrapper failed (exit {r.rc}): {r.err.strip()[-400:]}")
    stats = json.loads(lines[-1][len(MARK):])
    if stats["rc"] != 0:
        raise JudgeError(f"benchmark failed (exit {stats['rc']}): {r.err.strip()[-400:]}")
    return stats, "\n".join(lines[:-1])


def _result(out: str) -> str:
    """What a measured run produced, without the line of reported metrics (timings vary run to run)."""
    lines = out.strip().splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith("{"):
            del lines[i]
            break
    return "\n".join(line.rstrip() for line in lines).strip()


def _reported(out: str) -> dict[str, float]:
    for line in reversed(out.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return {k: float(v) for k, v in json.loads(line).items() if isinstance(v, (int, float))}
            except ValueError:
                return {}
    return {}


def _observe(spec: dict, observer_dir: Path, cfg: dict, env: dict, timeout: int) -> dict[str, float]:
    """Run the harness's observer after a workload run and return its metrics as observed.*.

    The observer comes from the base commit and runs in the base's directory, so a
    candidate cannot change it. Typically it queries telemetry (an OpenTelemetry
    collector, Prometheus, a proxy's access log) for this run's id and time window.
    """
    obs = (spec.get("measure") or {}).get("observer") or {}
    if not obs.get("run"):
        return {}
    r = run(obs["run"], observer_dir, cfg, env=env, timeout=timeout)
    if r.rc != 0:
        raise JudgeError(f"the observer failed (exit {r.rc}): {r.err.strip()[-400:]}")
    return {f"observed.{k}": v for k, v in _reported(r.out).items()}


def _score(spec: dict, scorer_dir: Path, env: dict, output: str, timeout: int) -> dict[str, float]:
    """Score one timed run's output outside the candidate, as scored.*.

    The scorer comes from the base commit, runs in the base's directory in its own process, and reads
    the run's output on stdin. It runs without a container: it is the judge's code, and it needs the
    private directory (MORPHOGEN_PRIVATE), which no candidate run is given."""
    sc = (spec.get("measure") or {}).get("score") or {}
    if not sc.get("run"):
        return {}
    env = dict(env)
    if sc.get("private"):
        env["MORPHOGEN_PRIVATE"] = sc["private"]
    r = run(sc["run"], scorer_dir, {"sandbox": "none"}, stdin=output, env=env, timeout=timeout)
    if r.rc != 0:
        raise JudgeError(f"the scorer failed (exit {r.rc}): {r.err.strip()[-400:]}")
    scores = {f"scored.{k}": v for k, v in _reported(r.out).items()}
    if not scores:
        raise JudgeError("the scorer printed no metrics (one JSON object of numbers on its last line)")
    return scores


def _prepare_score(spec: dict, repo: Path, rel: Path = Path("."), phase: str = "verdict") -> None:
    """Resolve the scorer's private directory; it must exist and lie outside the repository, where no
    commit (and so no candidate) can hold or read a copy. Probes score against `search` when it is
    given, so the optimizer's search never sees the held-out answers a verdict is scored on."""
    sc = (spec.get("measure") or {}).get("score") or {}
    if phase == "probe" and sc.get("search"):
        sc["private"] = sc["search"]
    if not sc.get("private"):
        return
    private = Path(sc["private"]).expanduser()
    private = (private if private.is_absolute() else repo / rel / private).resolve()  # relative: to the target
    if not private.is_dir():
        raise JudgeError(f"measure.score.private {sc['private']!r} is not a directory")
    try:
        private.relative_to(repo.resolve())
    except ValueError:
        sc["private"] = str(private)
        return
    raise JudgeError("measure.score.private must be outside the repository: a candidate's commit could "
                     "read or copy anything inside it")


def _names_private(spec: dict, ctree: Path, changed: list[str]) -> list[str]:
    """Changed files that name the scorer's private directory. target.yaml says where it is, and an
    agent can read target.yaml; without a container nothing stops a candidate opening that path, so a
    candidate that names it is refused. Obfuscating the path defeats this check: run in a container
    (only the candidate's tree is mounted) for the strong version."""
    private = ((spec.get("measure") or {}).get("score") or {}).get("private")
    if not private:
        return []
    needles = {private, Path(private).name} if len(Path(private).name) >= 8 else {private}
    hits = []
    for rel in changed:
        f = ctree / rel
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        if any(n in text for n in needles):
            hits.append(rel)
    return hits


def _cell_gate(cfg: dict, btree: Path, ctree: Path, cell: str | None) -> dict:
    """For a judgment of one cell: the structure from the base commit, the interfaces the cell's scope
    touches, and the base's copies of their test files laid over the candidate. Tests run later, in
    the candidate's tree, from the structure file's directory."""
    if not cell:
        return {"cell": None, "tests": [], "replaced": []}
    rel = Path(cfg.get("structure", "cells.yaml"))
    f = btree / rel
    if not f.exists():
        raise JudgeError(f"judging cell {cell!r} needs the structure ({rel}) on the base commit")
    s = Structure.load(f)
    if cell not in s.cells:
        raise JudgeError(f"no cell {cell!r} in the base's structure")
    scope = s.scope(cell)
    sdir_b, sdir_c = f.parent, ctree / rel.parent
    replaced = []
    # The structure itself, and every touched interface's files, come from the base.
    owned = [rel.name] + [x for i in s.touched(scope) for x in s.interfaces[i].files]
    for name in dict.fromkeys(owned):
        src, dst = sdir_b / name, sdir_c / name
        before = dst.read_bytes() if dst.exists() else None
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            if before != src.read_bytes():
                replaced.append(str(rel.parent / name))
    tests = [{"interface": i, "test": t} for i in s.touched(scope) for t in s.interfaces[i].tests]
    guard = None
    if s.cells[cell].guard is not False:
        ancestors, c = [], s.cells[cell].parent
        while c is not None and c in s.cells and c not in ancestors:
            ancestors.append(c)
            c = s.cells[c].parent
        top = next((a for a in reversed(ancestors) if s.cells[a].measure), None)
        if top is not None:
            opts = s.cells[cell].guard if isinstance(s.cells[cell].guard, dict) else {}
            guard = {"cell": top, "target": str(rel.parent / s.cells[top].measure),
                     "max_regression": float(opts.get("max_regression", 0.05))}
    return {"cell": cell, "scope": sorted(scope), "tests": tests, "replaced": replaced, "dir": sdir_c,
            "guard": guard}


def _system_guard(guard: dict, repo: Path, cfg: dict, btree: Path, ctree: Path, timeout: int) -> dict:
    """Measure the system around a judged cell, base against candidate, with every metric a constraint:
    a change that wins locally must not cost the whole (the system's primary metric may regress at
    most max_regression; other metrics keep their own limits). Paired rounds as for the verdict."""
    grel = Path(guard["target"])
    spec = load_spec(btree, grel)
    metrics = _check_spec(spec)
    _prepare_score(spec, repo, grel)
    _check_runner(spec, cfg)
    gb, gc = btree / grel, ctree / grel
    if not gc.exists():
        return {**guard, "ok": False, "reason": f"{grel} does not exist on the candidate"}
    _overlay(spec, gb, gc)
    constraints = {m: {**v, "primary": False,
                       "max_regression": guard["max_regression"] if v.get("primary")
                       else v.get("max_regression", 0.05)} for m, v in metrics.items()}
    m = spec["measure"]
    samples: list[dict[str, list[float]]] = [{}, {}]
    outputs: list = []
    seeds = []

    def round_(into):
        seeds.append(secrets.randbelow(2**31))
        _one_round(spec, [gb, gc], cfg, seeds[-1], timeout, into, gb, outputs=outputs)

    for _ in range(int(m.get("warmup", 1))):
        round_([{}, {}])
    outputs.clear()
    for _ in range(int(m.get("repeats", 10))):
        round_(samples)
    comparisons, undecided = _compare(constraints, *samples)
    while undecided and len(samples[0]["wall_seconds"]) < int(m.get("max_repeats", 30)):
        round_(samples)
        comparisons, undecided = _compare(constraints, *samples)
    mismatches = sum(1 for b, c in outputs if b != c) if m.get("same_output", True) else 0
    ok = not mismatches and all(c["ok"] for c in comparisons.values())
    return {**guard, "ok": ok, "metrics": comparisons, "timed_output_mismatches": mismatches, "seeds": seeds}


def _run_interface_tests(gate: dict, cfg: dict, timeout: int) -> list[dict]:
    out = []
    for t in gate["tests"]:
        r = run(t["test"], gate["dir"], cfg, timeout=timeout, private=True)
        out.append({**t, "passed": r.rc == 0, **({} if r.rc == 0 else {"output": _clip(r.err or r.out, 600)})})
    return out


def _one_round(spec: dict, dirs: list[Path], cfg: dict, seed: int, timeout: int,
               samples: list[dict[str, list[float]]], observer_dir: Path | None = None,
               sides: tuple[str, ...] = ("base", "candidate"), outputs: list | None = None) -> None:
    """One run per side. Order alternates between rounds (ABBA) so drift and warm-up hit both.
    With `outputs`, appends each side's result (stdout without reported metrics) for this round."""
    results = [""] * len(dirs)
    rnd = len(next(iter(samples[0].values()), []))
    order = list(range(len(dirs)))
    if rnd % 2:
        order.reverse()
    for i in order:
        run_id = secrets.token_hex(8)
        side = sides[i] if i < len(sides) else str(i)
        env = {"MORPHOGEN_SEED": str(seed), "MORPHOGEN_RUN_ID": run_id, "MORPHOGEN_SIDE": side,
               "OTEL_RESOURCE_ATTRIBUTES": f"morphogen.run_id={run_id},morphogen.side={side}"}
        start = time.time()
        stats, out = _timed(spec["measure"]["run"], dirs[i], cfg, env, timeout)
        results[i] = _result(out)
        env.update({"MORPHOGEN_RUN_START": f"{start:.6f}", "MORPHOGEN_RUN_END": f"{time.time():.6f}"})
        for k in JUDGE_METRICS:
            samples[i].setdefault(k, []).append(float(stats[k]))
        for k, v in _reported(out).items():
            samples[i].setdefault(f"reported.{k}", []).append(v)
        for k, v in _observe(spec, observer_dir or dirs[i], cfg, env, timeout).items():
            samples[i].setdefault(k, []).append(v)
        for k, v in _score(spec, observer_dir or dirs[i], env, results[i], timeout).items():
            samples[i].setdefault(k, []).append(v)
    if outputs is not None:
        outputs.append(results)


def _gain(b: float, c: float, lower: bool, absolute: bool = False) -> float:
    """Improvement of c over b: relative to b (the default), or in the metric's own units."""
    if absolute:
        return b - c if lower else c - b
    if not b:
        return 0.0
    return (b - c) / b if lower else (c - b) / b


def _sign_p(wins: int, n: int) -> float:
    """One-sided sign test: chance of at least `wins` of `n` pairs favouring the candidate by luck.
    Callers pass n without tied pairs, as the sign test requires."""
    return sum(math.comb(n, j) for j in range(wins, n + 1)) / 2 ** n if n else 1.0


def _paired(bs: list[float], cs: list[float], lower: bool, n: int = 2000, absolute: bool = False,
            aggregate: str = "median") -> dict:
    gains = [_gain(b, c, lower, absolute) for b, c in zip(bs, cs)]
    agg = statistics.fmean if aggregate == "mean" else statistics.median
    rng = random.Random(0)
    draws = sorted(agg(rng.choices(gains, k=len(gains))) for _ in range(n))
    return {"gains": gains, "point": agg(gains),
            "ci95": (draws[int(0.025 * n)], draws[int(0.975 * n) - 1])}


def _compare(metrics_spec: dict, bs: dict, cs: dict, alpha: float = 0.01) -> tuple[dict, bool]:
    """Per-metric comparison over paired rounds, and whether more rounds could change the verdict.

    Primary metric: passes when the paired gain (median by default, or `aggregate: mean`) clears
    the bar and a sign test says the candidate wins more pairs than luck explains (p <= alpha).
    Other metrics: fail only when a sign test says they regress beyond their limit.
    Tied pairs say nothing about which side is better and are left out of the sign test. Gains are
    relative to the base by default; `gain: absolute` uses the metric's units (for scores that can be 0).
    """
    out, undecided = {}, False
    for metric, ms in metrics_spec.items():
        if metric not in bs or metric not in cs:
            raise JudgeError(f"no measurements for {metric!r}")
        lower = ms.get("direction", "lower") == "lower"
        aggregate = ms.get("aggregate", "median")
        if aggregate not in ("median", "mean") or ms.get("gain", "relative") not in ("relative", "absolute"):
            raise JudgeError(f"{metric}: aggregate must be median or mean, gain relative or absolute")
        pr = _paired(bs[metric], cs[metric], lower, absolute=ms.get("gain") == "absolute", aggregate=aggregate)
        n = len(pr["gains"])
        untied = sum(g != 0 for g in pr["gains"])
        if ms.get("primary"):
            bar = float(ms.get("min_improvement", 0.05))
            p = _sign_p(sum(g > 0 for g in pr["gains"]), untied)
            ok = pr["point"] >= bar and p <= alpha
            undecided |= (not ok) and pr["point"] >= bar / 2
        else:
            limit = float(ms.get("max_regression", 0.05))
            p = _sign_p(sum(g < -limit for g in pr["gains"]), untied)
            ok = not (p <= alpha)
            undecided |= ok and pr["point"] < -limit
        out[metric] = {"base": statistics.median(bs[metric]), "candidate": statistics.median(cs[metric]),
                       "gain": round(pr["point"], 4), "ci95": [round(x, 4) for x in pr["ci95"]],
                       "sign_test_p": round(p, 5), "ok": ok, "primary": bool(ms.get("primary")), "runs": n,
                       "tied": n - untied, "gain_kind": ms.get("gain", "relative")}
    return out, undecided


def _check_runner(spec: dict, cfg: dict) -> None:
    gaps = missing(cfg, spec.get("requires") or [])
    if gaps:
        raise JudgeError(f"this target requires {', '.join(gaps)}, which the {sandbox_mode(cfg)} runner does not "
                         "provide; set sandbox: podman (or auto, with Podman installed) in morphogen.yaml")


def _check_spec(spec: dict) -> dict:
    m = spec.get("measure") or {}
    if not m.get("run"):
        raise JudgeError("target.yaml has no measure.run")
    metrics = m.get("metrics") or {}
    primaries = [k for k, v in metrics.items() if v.get("primary")]
    if len(primaries) != 1:
        raise JudgeError("target.yaml must mark exactly one metric as primary")
    primary = primaries[0]
    observer = m.get("observer") or {}
    if primary.startswith("observed."):
        if observer.get("collected") != "outside":
            raise JudgeError("an observed metric can be primary only if the observer's data is collected outside "
                             "the code under test (measure.observer.collected: outside)")
    elif primary.startswith("scored."):
        if not (m.get("score") or {}).get("run"):
            raise JudgeError("a scored metric can be primary only with a scorer (measure.score.run), "
                             "which reads each run's output outside the candidate")
    elif primary not in JUDGE_METRICS:
        raise JudgeError(f"the primary metric must be measured by the judge ({', '.join(JUDGE_METRICS)}), "
                         "observed outside the code under test (observed.*), or scored outside the "
                         "candidate (scored.*)")
    return metrics


def _trials_today(evidence, kind: str = "verdict") -> int:
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    return sum(1 for r in evidence.dump()
               if r.get("by") == "judge" and r.get("kind") == kind and str(r.get("at", "")).startswith(today))


def _clip(text: str, n: int = 300) -> str:
    text = text.strip()
    return text if len(text) <= n else text[:n] + f"... ({len(text) - n} more characters)"


def _clip_pair(expected: str, got: str, n: int = 300) -> tuple[str, str]:
    """Both outputs clipped to the same window, starting just before their first difference, so a
    difference past the first `n` characters still shows (a plain clip made them look identical)."""
    a, b = expected.strip(), got.strip()
    i = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    start = max(0, i - 60)

    def window(t: str) -> str:
        part = t[start:start + n]
        return ((f"({start} characters before) ..." if start else "") + part +
                (f"... ({len(t) - start - n} more characters)" if len(t) > start + n else ""))
    return window(a), window(b)


def probe(root: Path, cfg: dict, target: str, candidate: str, evidence, base: str | None = None,
          cases: int = 5, rounds: int = 3, cell: str | None = None) -> dict:
    """A practice run for strategies: feedback on a candidate, never a verdict.

    Same rules as the judge (the base's spec and harness laid over the candidate, the
    forbidden-file check, fresh random inputs), but it reports what a strategy needs to
    learn from: the check's output, each generated case with the base's output and the
    candidate's where they differ, and medians of a few paired timing rounds. It shows
    nothing a candidate could not already compute, since the generator and the base's code
    are in the repository. Recorded as evidence of kind `probe`; it cannot be proposed for
    merging, strategy selection ignores it, and it does not count against
    budget.trials_per_day (budget.probes_per_day caps it instead).
    """
    limit = int((cfg.get("budget") or {}).get("probes_per_day", 0) or 0)
    if limit and _trials_today(evidence, "probe") >= limit:
        raise JudgeError(f"the probe budget for today ({limit}) is spent; the operator can raise "
                         "budget.probes_per_day in morphogen.yaml")
    repo = repo_root(root)
    rel = (root / target).resolve().relative_to(repo)
    base_sha = resolve(repo, base or cfg.get("trunk", "main"))
    cand_sha = resolve(repo, candidate)
    changed = _changed(repo, base_sha, cand_sha, rel)
    out: dict = {"target": str(rel), "base": base_sha, "candidate": cand_sha, "binding": False}
    with worktrees(repo, [base_sha, cand_sha]) as (btree, ctree):
        spec = load_spec(btree, rel)
        metrics_spec = _check_spec(spec)
        _prepare_score(spec, repo, rel, "probe")
        _check_runner(spec, cfg)
        timeout = int(spec.get("timeout", 300))
        out["forbidden"] = _forbidden(changed, rel, list(spec.get("harness", [])))
        bdir, cdir = btree / rel, ctree / rel
        if not cdir.exists():
            raise JudgeError(f"{rel} does not exist on the candidate commit")
        _overlay(spec, bdir, cdir)
        out["parameters"], out["parameter_violations"] = _parameters(spec, bdir, cdir)
        named = _names_private(spec, ctree, changed)
        if named:
            out["parameter_violations"] = out["parameter_violations"] + [
                f"names the scorer's private directory (held-out answers): {', '.join(named)}"]
        gate = _cell_gate(cfg, btree, ctree, cell)
        if not out["forbidden"] and not out["parameter_violations"]:
            if gate["tests"]:
                out["interfaces"] = _run_interface_tests(gate, cfg, timeout)
            if spec.get("check"):
                r = run(spec["check"], cdir, cfg, timeout=timeout, private=True)
                out["check"] = {"passed": r.rc == 0, "output": "" if r.rc == 0 else _clip(r.err or r.out, 1200)}
            eq = spec.get("equivalence")
            if eq:
                results = []
                for _ in range(max(0, min(int(cases), 50))):
                    seed = secrets.randbelow(2**31)
                    g = run(eq["gen"].format(seed=seed), bdir, cfg, timeout=timeout)
                    ob = run(eq["run"], bdir, cfg, stdin=g.out, timeout=timeout, private=True)
                    oc = run(eq["run"], cdir, cfg, stdin=g.out, timeout=timeout, private=True)
                    case = {"seed": seed, "status": "failed" if oc.rc != 0 else
                            ("ok" if oc.out.strip() == ob.out.strip() else "wrong")}
                    if case["status"] != "ok":
                        if oc.rc == 0:
                            exp, got = _clip_pair(ob.out, oc.out)
                        else:
                            exp, got = _clip(ob.out), _clip(oc.err or oc.out)
                        case.update({"input": _clip(g.out, 200), "expected": exp, "got": got})
                    results.append(case)
                out["cases"] = results
            samples: list[dict[str, list[float]]] = [{}, {}]
            outputs: list = []
            for _ in range(max(0, min(int(rounds), 10))):
                _one_round(spec, [bdir, cdir], cfg, secrets.randbelow(2**31), timeout, samples, bdir,
                           outputs=outputs)
            if outputs:
                out["metrics"] = {
                    m: {"base": statistics.median(samples[0][m]), "candidate": statistics.median(samples[1][m]),
                        "gain": round(statistics.median(_gain(b, c, ms.get("direction", "lower") == "lower",
                                                              ms.get("gain") == "absolute")
                                                        for b, c in zip(samples[0][m], samples[1][m])), 4)}
                    for m, ms in metrics_spec.items() if m in samples[0] and m in samples[1]}
                out["timed_output_mismatches"] = sum(1 for b, c in outputs if b != c)
    rec = evidence.append({
        "claim": f"probe of {cand_sha[:12]} against {base_sha[:12]} (practice; not a verdict)",
        "kind": "probe", "subject": {"system": _target_name(spec, rel), "path": str(rel)},
        "refs": {"base": base_sha, "candidate": cand_sha}, "parameters": out["parameters"],
        "outcome": {k: v for k, v in out.items() if k in ("forbidden", "parameter_violations", "check", "metrics",
                                                          "timed_output_mismatches", "interfaces")}
        | {"cases": [{k: c[k] for k in ("seed", "status")} for c in out.get("cases", [])]},
        "sandbox": sandbox_mode(cfg), "trust": "measured", "by": "judge",
    })
    out["evidence_seq"] = rec["seq"]
    out["note"] = "practice only: only judge() can produce a verdict, and only a verdict can be proposed for merging"
    return out


def measure(root: Path, cfg: dict, target: str, ref: str, evidence) -> dict:
    repo = repo_root(root)
    rel = (root / target).resolve().relative_to(repo)
    sha = resolve(repo, ref)
    with worktrees(repo, [sha]) as (tree,):
        spec = load_spec(tree, rel)
        _check_spec(spec)
        _prepare_score(spec, repo, rel)
        _check_runner(spec, cfg)
        name = _target_name(spec, rel)
        interface, trust = _interface(spec)
        timeout = int(spec.get("timeout", 300))
        m = spec["measure"]
        seeds = []
        samples: list[dict[str, list[float]]] = [{}]
        for i in range(int(m.get("warmup", 1)) + int(m.get("repeats", 10))):
            seeds.append(secrets.randbelow(2**31))
            _one_round(spec, [tree / rel], cfg, seeds[-1], timeout, samples if i >= int(m.get("warmup", 1)) else [{}],
                       tree / rel, ("measured",))
    metrics = {k: statistics.median(v) for k, v in samples[0].items()}
    rec = evidence.append({
        "claim": f"{name} at {sha[:12]} measures {json.dumps({k: round(v, 6) for k, v in metrics.items()}, sort_keys=True)}",
        "kind": "measurement",
        "subject": {"system": name, "path": str(rel)},
        "method": f"median of {len(next(iter(samples[0].values())))} runs timed outside the process; random seed",
        "outcome": metrics,
        "refs": {"commit": sha},
        "seeds": {"bench": seeds},
        "interface": interface,
        **({"simulates": spec["simulates"]} if interface == "simulated" else {}),
        "sandbox": sandbox_mode(cfg),
        "runner": capabilities(cfg),
        "trust": trust,
        "by": "judge",
    })
    out = {"target": name, "commit": sha, "metrics": metrics, "interface": interface, "trust": trust,
           "sandbox": rec["sandbox"], "evidence_seq": rec["seq"]}
    if interface == "simulated":
        out["note"] = SIMULATED_NOTE.format(what=spec["simulates"])
    return out


def judge(root: Path, cfg: dict, target: str, base: str, candidate: str, evidence,
          labels: dict | None = None, cell: str | None = None) -> dict:
    """Score `candidate` against `base`. `labels` (strategy, approach, family) are recorded with the
    verdict for the archive and never affect it."""
    limit = int((cfg.get("budget") or {}).get("trials_per_day", 0) or 0)
    if limit and _trials_today(evidence) >= limit:
        raise JudgeError(f"the trial budget for today ({limit}) is spent; the operator can raise "
                         "budget.trials_per_day in morphogen.yaml")
    repo = repo_root(root)
    rel = (root / target).resolve().relative_to(repo)
    base_sha, cand_sha = resolve(repo, base), resolve(repo, candidate)
    changed = _changed(repo, base_sha, cand_sha, rel)
    with worktrees(repo, [base_sha, cand_sha]) as (btree, ctree):
        spec = load_spec(btree, rel)
        forbidden = _forbidden(changed, rel, list(spec.get("harness", [])))
        metrics_spec = _check_spec(spec)
        _prepare_score(spec, repo, rel)
        _check_runner(spec, cfg)
        name = _target_name(spec, rel)
        interface, trust = _interface(spec)
        timeout = int(spec.get("timeout", 300))
        harness = set(spec.get("harness", [])) | {"target.yaml"}
        harness_touched = [p for p in changed if str(Path(p).relative_to(rel)) in harness]
        bdir, cdir = btree / rel, ctree / rel
        if not cdir.exists():
            raise JudgeError(f"{rel} does not exist on the candidate commit")
        _overlay(spec, bdir, cdir)
        parameters, param_violations = _parameters(spec, bdir, cdir)
        names_private = _names_private(spec, ctree, changed)
        if names_private:
            param_violations = param_violations + [
                f"names the scorer's private directory (held-out answers): {', '.join(names_private)}"]
        gate = _cell_gate(cfg, btree, ctree, cell)
        refused = bool(forbidden or param_violations)  # refused before anything runs

        check_ok, check_detail = True, "no check defined"
        if spec.get("check") and not refused:
            r = run(spec["check"], cdir, cfg, timeout=timeout, private=True)
            check_ok = r.rc == 0
            check_detail = "passed" if check_ok else (r.err or r.out).strip()[-600:]
        interface_results = _run_interface_tests(gate, cfg, timeout) if not refused else []
        interfaces_ok = all(x["passed"] for x in interface_results)
        check_ok = check_ok and interfaces_ok

        eq = spec.get("equivalence")
        eq_seeds, mismatches, failures = [], 0, 0
        if eq and not refused:
            for _ in range(int(eq.get("cases", 5))):
                seed = secrets.randbelow(2**31)
                eq_seeds.append(seed)
                g = run(eq["gen"].format(seed=seed), bdir, cfg, timeout=timeout)
                if g.rc != 0:
                    raise JudgeError(f"input generator failed on the base: {g.err.strip()[-400:]}")
                ob = run(eq["run"], bdir, cfg, stdin=g.out, timeout=timeout, private=True)
                if ob.rc != 0:
                    raise JudgeError(f"the base failed on a generated input: {ob.err.strip()[-400:]}")
                oc = run(eq["run"], cdir, cfg, stdin=g.out, timeout=timeout, private=True)
                if oc.rc != 0:
                    failures += 1
                elif oc.out.strip() != ob.out.strip():
                    mismatches += 1
        equivalent = mismatches == 0 and failures == 0

        comparisons, perf_ok, bench_seeds, outputs, timed_mismatches, system = {}, False, [], [], 0, None
        if check_ok and equivalent and not refused:
            m = spec["measure"]
            # A fresh seed every round: base and candidate share it within a round (a fair pair),
            # but no two rounds see the same input, so nothing learned in one round helps the next.
            bench_seeds, outputs = [], []

            def round_(samples):
                bench_seeds.append(secrets.randbelow(2**31))
                _one_round(spec, dirs, cfg, bench_seeds[-1], timeout, samples, bdir, outputs=outputs)

            dirs = [bdir, cdir]
            for _ in range(int(m.get("warmup", 1))):
                round_([{}, {}])
            samples: list[dict[str, list[float]]] = [{}, {}]
            for _ in range(int(m.get("repeats", 10))):
                round_(samples)
            comparisons, undecided = _compare(metrics_spec, *samples)
            while undecided and len(samples[0]["wall_seconds"]) < int(m.get("max_repeats", 30)):
                round_(samples)
                comparisons, undecided = _compare(metrics_spec, *samples)
            # The timed runs must produce what the base produces on the same input. Otherwise code
            # that can tell a timed run from a checked one (an environment variable, argv, the caller)
            # could do less work only when timed. Opt out only for workloads whose output varies.
            if m.get("same_output", True):
                timed_mismatches = sum(1 for b, c in outputs if b != c)
            perf_ok = not timed_mismatches and all(c["ok"] for c in comparisons.values())
            if perf_ok and gate.get("guard"):
                system = _system_guard(gate["guard"], repo, cfg, btree, ctree, timeout)
                perf_ok = system["ok"]

    passed = not refused and check_ok and equivalent and perf_ok
    reasons = []
    if forbidden:
        reasons.append(f"changes files that shadow standard or harness modules, or customise Python: "
                       f"{', '.join(forbidden)}")
    reasons += param_violations
    if system and not system["ok"]:
        worst = [f"{k} {c['gain']:+.1%}" for k, c in (system.get("metrics") or {}).items() if not c["ok"]]
        reasons.append(f"the system ({system['cell']}, {system['target']}) gets worse: "
                       + (", ".join(worst) or system.get("reason") or
                          f"{system.get('timed_output_mismatches')} runs changed its output"))
    for x in interface_results:
        if not x["passed"]:
            reasons.append(f"interface {x['interface']}: its test fails on the candidate ({x['test']})")
    if not check_ok and interfaces_ok:
        reasons.append("the base's tests fail on the candidate")
    if not equivalent:
        reasons.append(f"{mismatches} wrong and {failures} failed outputs on {len(eq_seeds)} generated inputs")
    if timed_mismatches:
        reasons.append(f"{timed_mismatches} of {len(outputs)} timed runs gave different output from the base "
                       "on the same input")
    for metric, c in comparisons.items():
        if not c["ok"]:
            reasons.append(f"{metric}: gain {c['gain']:+.1%} (95% interval {c['ci95'][0]:+.1%} to "
                           f"{c['ci95'][1]:+.1%}, sign test p={c['sign_test_p']}) does not meet the bar")
    notes = [f"harness files changed by the candidate were replaced by the base's: {', '.join(harness_touched)}"] \
        if harness_touched else []
    if gate["replaced"]:
        notes.append(f"structure and interface test files changed by the candidate were replaced by the base's: "
                     f"{', '.join(gate['replaced'])}")
    if interface == "simulated":
        notes.append(SIMULATED_NOTE.format(what=spec["simulates"]))
    verdict = "pass" if passed else "fail"
    rec = evidence.append({
        "claim": f"{name}: {cand_sha[:12]} is {'better than' if passed else 'not better than'} {base_sha[:12]}",
        "kind": "verdict",
        "verdict": verdict,
        "subject": {"system": name, "path": str(rel)},
        "method": "base's spec and harness; forbidden-file check; declared parameters; base's tests; "
                  "output equivalence on fresh "
                  "random inputs; paired ABBA runs timed outside the process, each checked for the base's "
                  "output; sign test",
        "outcome": {"forbidden": forbidden, "parameter_violations": param_violations,
                    "check": check_ok, "interfaces": interface_results, "system": system,
                    "generated_inputs": len(eq_seeds),
                    "wrong": mismatches, "failed": failures, "timed_output_mismatches": timed_mismatches,
                    "metrics": comparisons},
        "refs": {"base": base_sha, "candidate": cand_sha},
        "parameters": parameters,
        **({"cell": cell, "scope": gate["scope"]} if cell else {}),
        "seeds": {"equivalence": eq_seeds, "bench": bench_seeds},
        "labels": {str(k): str(v) for k, v in (labels or {}).items()},
        "interface": interface,
        **({"simulates": spec["simulates"]} if interface == "simulated" else {}),
        "sandbox": sandbox_mode(cfg),
        "runner": capabilities(cfg),
        "trust": trust,
        "by": "judge",
    })
    return {
        "verdict": verdict,
        "target": name,
        "base": base_sha,
        "candidate": cand_sha,
        "parameters": parameters,
        "check": check_detail if not check_ok else "passed",
        "cell": cell,
        "interfaces": interface_results,
        "system": system,
        "generated_inputs": {"cases": len(eq_seeds), "wrong": mismatches, "failed": failures},
        "metrics": comparisons,
        "reasons": reasons,
        "notes": notes,
        "interface": interface,
        "trust": trust,
        "sandbox": rec["sandbox"],
        "evidence_seq": rec["seq"],
    }
