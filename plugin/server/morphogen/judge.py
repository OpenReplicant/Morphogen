"""The judge: score a candidate commit against a base commit, by the base's rules.

- The target's spec (`target.yaml`) and its harness files (benchmark, tests,
  input generator) are taken from the base commit and laid over the
  candidate, so a candidate cannot change how it is scored.
- Correctness: the base's tests must pass on the candidate, and the candidate
  must give the same output as the base on hidden inputs whose seeds only the
  judge knows.
- Performance: the benchmark runs alternately on base and candidate with a
  hidden seed; medians are compared per metric.
- The verdict is written to the evidence log as `trust: measured, by: judge`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import statistics
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

import yaml

from .config import judge_secret
from .runner import run, sandbox_mode


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


def _seed(secret: bytes, target: str, label: str, i: int) -> int:
    d = hmac.new(secret, f"{target}:{label}:{i}".encode(), hashlib.sha256).digest()
    return int.from_bytes(d[:4], "big")


def _overlay(spec: dict, base_dir: Path, cand_dir: Path) -> list[str]:
    """Copy the base's harness files over the candidate's."""
    done = []
    for name in spec.get("harness", []) + ["target.yaml"]:
        src, dst = base_dir / name, cand_dir / name
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        elif dst.exists():
            dst.unlink()
        done.append(name)
    return done


def _last_json(text: str) -> dict:
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise JudgeError("the benchmark printed no JSON line")


def _bench(spec: dict, dirs: list[Path], cfg: dict, seed: int, timeout: int) -> list[dict[str, float]]:
    m = spec.get("measure") or {}
    if not m.get("run"):
        raise JudgeError("target.yaml has no measure.run")
    repeats = int(m.get("repeats", 3))
    samples: list[dict[str, list[float]]] = [{} for _ in dirs]
    for _ in range(repeats):
        for i, d in enumerate(dirs):  # alternate sides so drift hits both
            r = run(m["run"], d, cfg, env={"MORPHOGEN_SEED": str(seed)}, timeout=timeout)
            if r.rc != 0:
                raise JudgeError(f"benchmark failed (exit {r.rc}): {r.err.strip()[-400:]}")
            for k, v in _last_json(r.out).items():
                samples[i].setdefault(k, []).append(float(v))
    return [{k: statistics.median(v) for k, v in s.items()} for s in samples]


def _target_name(spec: dict, rel: Path) -> str:
    return spec.get("name") or rel.name


def measure(root: Path, cfg: dict, target: str, ref: str, evidence) -> dict:
    repo = repo_root(root)
    rel = (root / target).resolve().relative_to(repo)
    sha = resolve(repo, ref)
    with worktrees(repo, [sha]) as (tree,):
        spec = load_spec(tree, rel)
        name = _target_name(spec, rel)
        timeout = int(spec.get("timeout", 300))
        seed = _seed(judge_secret(root), name, "bench", 0)
        (metrics,) = _bench(spec, [tree / rel], cfg, seed, timeout)
    rec = evidence.append({
        "claim": f"{name} at {sha[:12]} measures {json.dumps(metrics, sort_keys=True)}",
        "kind": "measurement",
        "subject": {"system": name, "path": str(rel)},
        "method": f"median of {spec.get('measure', {}).get('repeats', 3)} runs with a hidden seed",
        "outcome": metrics,
        "refs": {"commit": sha},
        "sandbox": sandbox_mode(cfg),
        "trust": "measured",
        "by": "judge",
    })
    return {"target": name, "commit": sha, "metrics": metrics, "sandbox": rec["sandbox"], "evidence_seq": rec["seq"]}


def judge(root: Path, cfg: dict, target: str, base: str, candidate: str, evidence) -> dict:
    repo = repo_root(root)
    rel = (root / target).resolve().relative_to(repo)
    base_sha, cand_sha = resolve(repo, base), resolve(repo, candidate)
    secret = judge_secret(root)
    with worktrees(repo, [base_sha, cand_sha]) as (btree, ctree):
        spec = load_spec(btree, rel)
        name = _target_name(spec, rel)
        timeout = int(spec.get("timeout", 300))
        bdir, cdir = btree / rel, ctree / rel
        if not cdir.exists():
            raise JudgeError(f"{rel} does not exist on the candidate commit")
        _overlay(spec, bdir, cdir)

        check_ok, check_detail = True, "no check defined"
        if spec.get("check"):
            r = run(spec["check"], cdir, cfg, timeout=timeout)
            check_ok = r.rc == 0
            check_detail = "passed" if check_ok else (r.err or r.out).strip()[-600:]

        eq = spec.get("equivalence")
        cases, mismatches, failures = 0, 0, 0
        if eq:
            cases = int(eq.get("cases", 5))
            for i in range(cases):
                seed = _seed(secret, name, "eq", i)
                g = run(eq["gen"].format(seed=seed), bdir, cfg, timeout=timeout)
                if g.rc != 0:
                    raise JudgeError(f"input generator failed on the base: {g.err.strip()[-400:]}")
                ob = run(eq["run"], bdir, cfg, stdin=g.out, timeout=timeout)
                if ob.rc != 0:
                    raise JudgeError(f"the base failed on a hidden input: {ob.err.strip()[-400:]}")
                oc = run(eq["run"], cdir, cfg, stdin=g.out, timeout=timeout)
                if oc.rc != 0:
                    failures += 1
                elif oc.out.strip() != ob.out.strip():
                    mismatches += 1
        equivalent = mismatches == 0 and failures == 0

        metrics_spec = (spec.get("measure") or {}).get("metrics") or {}
        comparisons, perf_ok = {}, True
        if check_ok and equivalent:
            seed = _seed(secret, name, "bench", 0)
            bm, cm = _bench(spec, [bdir, cdir], cfg, seed, timeout)
            for metric, ms in metrics_spec.items():
                if metric not in bm or metric not in cm:
                    raise JudgeError(f"benchmark did not report {metric!r}")
                b, c = bm[metric], cm[metric]
                lower = ms.get("direction", "lower") == "lower"
                gain = ((b - c) / b if lower else (c - b) / b) if b else 0.0
                if ms.get("primary"):
                    ok = gain >= float(ms.get("min_improvement", 0.05))
                else:
                    ok = gain >= -float(ms.get("max_regression", 0.05))
                perf_ok &= ok
                comparisons[metric] = {"base": b, "candidate": c, "gain": round(gain, 4), "ok": ok,
                                       "primary": bool(ms.get("primary"))}
        else:
            perf_ok = False

    passed = check_ok and equivalent and perf_ok
    reasons = []
    if not check_ok:
        reasons.append("the base's tests fail on the candidate")
    if not equivalent:
        reasons.append(f"{mismatches} wrong and {failures} failed outputs on {cases} hidden inputs")
    for metric, c in comparisons.items():
        if not c["ok"]:
            reasons.append(f"{metric}: gain {c['gain']:+.1%} does not meet the bar")
    verdict = "pass" if passed else "fail"
    rec = evidence.append({
        "claim": f"{name}: {cand_sha[:12]} is {'better than' if passed else 'not better than'} {base_sha[:12]}",
        "kind": "verdict",
        "verdict": verdict,
        "subject": {"system": name, "path": str(rel)},
        "method": "base's tests and harness; output equivalence on hidden inputs; "
                  "alternating benchmark runs with a hidden seed, medians compared",
        "outcome": {"check": check_ok, "hidden_cases": cases, "wrong": mismatches, "failed": failures,
                    "metrics": comparisons},
        "refs": {"base": base_sha, "candidate": cand_sha},
        "sandbox": sandbox_mode(cfg),
        "trust": "measured",
        "by": "judge",
    })
    return {
        "verdict": verdict,
        "target": name,
        "base": base_sha,
        "candidate": cand_sha,
        "check": check_detail if not check_ok else "passed",
        "hidden_inputs": {"cases": cases, "wrong": mismatches, "failed": failures},
        "metrics": comparisons,
        "reasons": reasons,
        "sandbox": rec["sandbox"],
        "evidence_seq": rec["seq"],
    }
