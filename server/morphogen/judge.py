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
  A gain counts only if the median paired gain clears the bar and a sign test
  says the candidate wins more pairs than luck explains (p <= 0.01); close
  calls get more rounds, up to a limit.
- Every verdict is written to the evidence log as `trust: measured, by: judge`.
"""

from __future__ import annotations

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
from contextlib import contextmanager
from pathlib import Path

import yaml

from .ports import INTERFACES
from .runner import capabilities, run, sandbox_mode

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
    return yaml.safe_load(f.read_text()) or {}


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
    if outputs is not None:
        outputs.append(results)


def _gain(b: float, c: float, lower: bool) -> float:
    if not b:
        return 0.0
    return (b - c) / b if lower else (c - b) / b


def _sign_p(wins: int, n: int) -> float:
    """One-sided sign test: chance of at least `wins` of `n` pairs favouring the candidate by luck."""
    return sum(math.comb(n, j) for j in range(wins, n + 1)) / 2 ** n if n else 1.0


def _paired(bs: list[float], cs: list[float], lower: bool, n: int = 2000) -> dict:
    gains = [_gain(b, c, lower) for b, c in zip(bs, cs)]
    rng = random.Random(0)
    draws = sorted(statistics.median(rng.choices(gains, k=len(gains))) for _ in range(n))
    return {"gains": gains, "point": statistics.median(gains),
            "ci95": (draws[int(0.025 * n)], draws[int(0.975 * n) - 1])}


def _compare(metrics_spec: dict, bs: dict, cs: dict, alpha: float = 0.01) -> tuple[dict, bool]:
    """Per-metric comparison over paired rounds, and whether more rounds could change the verdict.

    Primary metric: passes when the median paired gain clears the bar and a sign
    test says the candidate wins more pairs than luck explains (p <= alpha).
    Other metrics: fail only when a sign test says they regress beyond their limit.
    """
    out, undecided = {}, False
    for metric, ms in metrics_spec.items():
        if metric not in bs or metric not in cs:
            raise JudgeError(f"no measurements for {metric!r}")
        lower = ms.get("direction", "lower") == "lower"
        pr = _paired(bs[metric], cs[metric], lower)
        n = len(pr["gains"])
        if ms.get("primary"):
            bar = float(ms.get("min_improvement", 0.05))
            p = _sign_p(sum(g > 0 for g in pr["gains"]), n)
            ok = pr["point"] >= bar and p <= alpha
            undecided |= (not ok) and pr["point"] >= bar / 2
        else:
            limit = float(ms.get("max_regression", 0.05))
            p = _sign_p(sum(g < -limit for g in pr["gains"]), n)
            ok = not (p <= alpha)
            undecided |= ok and pr["point"] < -limit
        out[metric] = {"base": statistics.median(bs[metric]), "candidate": statistics.median(cs[metric]),
                       "gain": round(pr["point"], 4), "ci95": [round(x, 4) for x in pr["ci95"]],
                       "sign_test_p": round(p, 5), "ok": ok, "primary": bool(ms.get("primary")), "runs": n}
    return out, undecided


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
    elif primary not in JUDGE_METRICS:
        raise JudgeError(f"the primary metric must be measured by the judge ({', '.join(JUDGE_METRICS)}) "
                         "or observed outside the code under test (observed.*)")
    return metrics


def _trials_today(evidence) -> int:
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    return sum(1 for r in evidence.dump()
               if r.get("by") == "judge" and r.get("kind") == "verdict" and str(r.get("at", "")).startswith(today))


def measure(root: Path, cfg: dict, target: str, ref: str, evidence) -> dict:
    repo = repo_root(root)
    rel = (root / target).resolve().relative_to(repo)
    sha = resolve(repo, ref)
    with worktrees(repo, [sha]) as (tree,):
        spec = load_spec(tree, rel)
        _check_spec(spec)
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
          labels: dict | None = None) -> dict:
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
        name = _target_name(spec, rel)
        interface, trust = _interface(spec)
        timeout = int(spec.get("timeout", 300))
        harness = set(spec.get("harness", [])) | {"target.yaml"}
        harness_touched = [p for p in changed if str(Path(p).relative_to(rel)) in harness]
        bdir, cdir = btree / rel, ctree / rel
        if not cdir.exists():
            raise JudgeError(f"{rel} does not exist on the candidate commit")
        _overlay(spec, bdir, cdir)

        check_ok, check_detail = True, "no check defined"
        if spec.get("check") and not forbidden:
            r = run(spec["check"], cdir, cfg, timeout=timeout, private=True)
            check_ok = r.rc == 0
            check_detail = "passed" if check_ok else (r.err or r.out).strip()[-600:]

        eq = spec.get("equivalence")
        eq_seeds, mismatches, failures = [], 0, 0
        if eq and not forbidden:
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

        comparisons, perf_ok, bench_seeds, outputs, timed_mismatches = {}, False, [], [], 0
        if check_ok and equivalent and not forbidden:
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

    passed = not forbidden and check_ok and equivalent and perf_ok
    reasons = []
    if forbidden:
        reasons.append(f"changes files that shadow standard or harness modules, or customise Python: "
                       f"{', '.join(forbidden)}")
    if not check_ok:
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
    if interface == "simulated":
        notes.append(SIMULATED_NOTE.format(what=spec["simulates"]))
    verdict = "pass" if passed else "fail"
    rec = evidence.append({
        "claim": f"{name}: {cand_sha[:12]} is {'better than' if passed else 'not better than'} {base_sha[:12]}",
        "kind": "verdict",
        "verdict": verdict,
        "subject": {"system": name, "path": str(rel)},
        "method": "base's spec and harness; forbidden-file check; base's tests; output equivalence on fresh "
                  "random inputs; paired ABBA runs timed outside the process, each checked for the base's "
                  "output; sign test",
        "outcome": {"forbidden": forbidden, "check": check_ok, "generated_inputs": len(eq_seeds),
                    "wrong": mismatches, "failed": failures, "timed_output_mismatches": timed_mismatches,
                    "metrics": comparisons},
        "refs": {"base": base_sha, "candidate": cand_sha},
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
        "check": check_detail if not check_ok else "passed",
        "generated_inputs": {"cases": len(eq_seeds), "wrong": mismatches, "failed": failures},
        "metrics": comparisons,
        "reasons": reasons,
        "notes": notes,
        "interface": interface,
        "trust": trust,
        "sandbox": rec["sandbox"],
        "evidence_seq": rec["seq"],
    }
