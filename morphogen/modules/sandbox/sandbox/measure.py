"""One experiment: a candidate provider and the slot's incumbent, each checked against the slot's
contract and measured on a copy of the record (R5-21).

An experiment is a directory `intent/experiments/<id>/` with `experiment.yaml`:

  slot: analyser
  incumbent: morphogen/modules/anomaly          # relative to the repository
  candidate: anomaly-recent                     # a provider directory inside the experiment
  request: urn:kk:request:...                   # what asked for it (optional)

Both are copied into a private directory first and run from there, so neither can change the code that
was measured or the other's results. For each of the two providers it
  1. runs the slot's contract (kernel/contract/run.py on the provider's directory, with the slot's own
     runner when the case set names one) and, when the slot has them (service.py beside its cases), its
     service cases: every case loaded into a fresh database and judged on what one pass of the provider
     submits (R5-23); cases passed of total, both counted together;
  2. creates a sandbox database, installs the kernel and Morphogen's modules, and copies into it the
     claims the slot's benchmark names (morphogen/contract/slots/<slot>/benchmark.yaml), read from the
     record under the sandbox's own clearance, each referencing the claim it copies;
  3. times full passes of the provider there from this process (driver.py runs its benchmark entry,
     `<package>.__main__.one_pass(conn)`, one pass per signal), adding one new window of input before
     each pass, as production does, so no pass can skip its work; the mean of the timed passes is the
     metric; then drops the database;
  4. writes `<experiment>-<incumbent|candidate>.json` in the private directory ({"provider", "slot",
     "dataset", "contract", "metric"}) for the evaluator, which records it as DQV measurements.

Provider code runs with none of this process's credentials: the contract with no database settings at
all, the service as the incumbent's own login (provider.yaml `role`, `login`; morphogen.logins), which a
candidate shares; an incumbent that declares no login is not measured. The metric is this process's clock,
not the provider's telemetry (R5-23); provider code that runs in the driver's process could still cheat it
(a pass that returns before its work is done), which the person reviewing the candidate's code sees.

The sandbox writes no claims itself: the evaluator records the scores, and this module's run records
what it did. Creating databases needs a superuser login for the sandbox's cluster (the PG* environment);
the record is read through DATABASE_URL as KK_ROLE.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import select
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
from psycopg.types.json import Jsonb

from kk.lib import connect
from morphogen.logins import KEEP, login_env, login_of

ROOT = Path(__file__).resolve().parents[4]
CONTRACT = ROOT / "morphogen" / "contract"
PASSED = re.compile(r"^\S+: (\d+)/(\d+) contract cases passed$", re.M)


def contract(provider_dir: Path) -> dict:
    """The slot contract on one provider: {"passed", "total"} (0 of 0 when the slot has none)."""
    out = subprocess.run([sys.executable, str(ROOT / "kernel" / "contract" / "run.py"),
                          "--blueprint", str(ROOT / "kernel" / "blueprint" / "slots.yaml"),
                          "--blueprint", str(ROOT / "morphogen" / "distribution.yaml"),
                          "--providers", str(provider_dir.parent), provider_dir.name],
                         capture_output=True, text=True,
                         env={**{k: v for k, v in os.environ.items() if k in KEEP and not k.startswith("PG")},
                              "PYTHONPATH": pythonpath(provider_dir)})
    m = PASSED.search(out.stdout)
    return {"passed": int(m.group(1)), "total": int(m.group(2))} if m else {"passed": 0, "total": 0}


def pythonpath(d: Path) -> str:
    return os.pathsep.join(filter(None, [str(d), str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "src"),
                                         os.environ.get("PYTHONPATH")]))


def inputs(record, predicates: list[str]) -> dict[str, list[dict]]:
    """scope -> add_claim ops copying the current claims with these predicates that the role may read.
    Extracted claims are not copied (a copy would need their quote): none of the benchmarks reads them."""
    rows = record.execute("""select id, subject, predicate, object_entity, object_value, qualifiers, valid_from,
                                    valid_to, evidence_type, scope from api.claims
                             where predicate = any(%s) and status <> 'deprecated' and redacted_at is null
                               and evidence_type <> 'extracted'""",
                          (predicates,)).fetchall()
    out: dict[str, list[dict]] = {}
    for cid, s, p, oe, ov, q, vf, vt, ev, scope in rows:
        op = {"op": "add_claim", "subject": s, "predicate": p,
              "object": {"entity": oe} if oe is not None else {"value": ov}, "qualifiers": q or {},
              "evidence_type": ev,
              "references": [{"source_uri": f"urn:kk:claim:{cid}"}]}
        if vf:
            op["valid_from"] = vf.isoformat()
        if vt:
            op["valid_to"] = vt.isoformat()
        out.setdefault(scope, []).append(op)
    return out


DRIVER = Path(__file__).resolve().parent / "driver.py"


def pass_times(provider_dir: Path, db: str, bench: dict, login: tuple[str, str], between) -> dict:
    """Time the provider's passes from this process (R5-23): its `<package>.__main__.<entry>(conn)`, run by
    driver.py as `login` (role, login) on the sandbox database. `between()` changes the record before each
    pass, as production does, so a pass cannot skip its work because nothing changed. The first `warmup`
    passes are not counted. Returns {"passes", "mean", "times"} or {"error"}."""
    meta = yaml.safe_load((provider_dir / "provider.yaml").read_text())
    m = re.fullmatch(r"python3 -m ([a-z_][a-z0-9_]*)", str(meta.get("service", "")))
    if not m:
        return {"error": "the service must be python3 -m <package>"}
    env = login_env(f"dbname={db}", *login, {"PYTHONPATH": pythonpath(provider_dir), "PYTHONDONTWRITEBYTECODE": "1"})
    p = subprocess.Popen([sys.executable, str(DRIVER), m.group(1), bench.get("entry", "one_pass")], cwd=provider_dir,
                         env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    limit = float(bench.get("pass_timeout", 60))

    def line() -> str:
        ready, _, _ = select.select([p.stdout], [], [], limit)
        return p.stdout.readline().strip() if ready else "timeout"
    times, err = [], None
    try:
        if (got := line()) != "ready":
            err = f"the driver did not start ({got})"
        for i in range(int(bench.get("warmup", 1)) + int(bench.get("passes", 5)) if err is None else 0):
            between()
            t0 = time.perf_counter()
            p.stdin.write("pass\n")
            p.stdin.flush()
            got = line()
            dt = time.perf_counter() - t0
            if got != "done":
                err = f"pass {i + 1}: {got}"
                break
            if i >= int(bench.get("warmup", 1)):
                times.append(round(dt, 6))
    finally:
        p.kill()
        _, stderr = p.communicate()
    if err:
        return {"error": (err + " " + (stderr or "").strip()[-300:]).strip()}
    return {"passes": len(times), "mean": round(sum(times) / len(times), 6), "times": times}


def between_passes(db: str, ops_by_scope: dict[str, list[dict]]):
    """A function adding, each time it is called, one new window of the newest copied input series: the
    change production sees between passes."""
    seed = max((op for ops in ops_by_scope.values() for op in ops if op.get("valid_from") and op.get("valid_to")),
               key=lambda op: op["valid_from"], default=None)
    scope = next((sc for sc, ops in ops_by_scope.items() if seed in ops), None)
    count = [0]

    def add() -> None:
        if seed is None:
            return
        count[0] += 1
        start, end = datetime.fromisoformat(seed["valid_from"]), datetime.fromisoformat(seed["valid_to"])
        shift = (end - start) * count[0]
        op = {**seed, "valid_from": (start + shift).isoformat(), "valid_to": (end + shift).isoformat(),
              "references": [{"source_uri": f"urn:kk:sandbox:between:{count[0]}"}]}
        with connect(url=f"dbname={db}") as su:
            su.execute("set role kk_owner")
            su.execute("select kernel.install_ops(%s, %s, %s)", (f"sandbox:between:{count[0]}", scope, Jsonb([op])))
    return add


def sandbox_db(name: str, ops_by_scope: dict[str, list[dict]]) -> None:
    sys.path.insert(0, str(ROOT / "morphogen" / "modules"))
    import importlib
    install = importlib.import_module("install")         # morphogen/modules/install.py
    subprocess.run(["dropdb", "--if-exists", name], check=True, capture_output=True)
    install.install(name, install.modules())
    with connect(url=f"dbname={name}") as su:
        su.execute("set role kk_owner")
        for scope, ops in sorted(ops_by_scope.items()):
            if su.execute("select 1 from kernel.scope where iri = %s", (scope,)).fetchone() is None:
                su.execute("insert into kernel.scope(iri, label) values (%s, %s)", (scope, scope))
            su.execute("select kernel.install_ops(%s, %s, %s)", (f"sandbox:inputs:{scope}", scope, Jsonb(ops)))


def service_cases(provider_dir: Path, slot: str, bench: dict, login: tuple[str, str], db: str) -> dict | None:
    """The slot's service cases (morphogen/contract/slots/<slot>/service.py), if it has them: every case
    loaded into a fresh database, one pass of the provider as `login`, the change sets it submitted judged
    by the slot's code. {"passed", "total", "failed"}; None when the slot has no service cases."""
    f = CONTRACT / "slots" / slot / "service.py"
    if not f.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"service_{slot}", f)
    svc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(svc)
    ops, expected = svc.ops(sorted((CONTRACT / "slots" / slot / "cases").glob("*.yaml")))
    try:
        sandbox_db(db, {"urn:kk:scope:default": ops})
        with connect(url=f"dbname={db}") as su:
            ids = {cid: got for cid, uri in su.execute("select claim_id::text, source_uri from kernel.claim_reference "
                                                       "where source_uri like 'urn:kk:case:%%'").fetchall()
                   if (got := svc.ref(uri))}
            before = {r[0] for r in su.execute("select id from kernel.change_set").fetchall()}
        ran = pass_times(provider_dir, db, {**bench, "warmup": 0, "passes": 1}, login, lambda: None)
        if "error" in ran:
            return {"passed": 0, "total": len(expected), "failed": ["(the pass failed)"], "error": ran["error"]}
        with connect(url=f"dbname={db}") as su:
            sets = [ops for cid, ops in su.execute("select id, ops from kernel.change_set").fetchall() if cid not in before]
    finally:
        subprocess.run(["dropdb", "--if-exists", db], capture_output=True)
    return svc.judge(sets, ids, expected)


def measure(provider_dir: Path, slot: str, record, exp_id: str, bench: dict, ops_by_scope: dict,
            login: tuple[str, str]) -> dict:
    """The provider's contract (the slot's rule cases, plus its service cases when it has them, counted
    together) and its benchmark."""
    meta = yaml.safe_load((provider_dir / "provider.yaml").read_text())
    db = "kk_sbx_" + re.sub(r"[^a-z0-9]", "_", f"{exp_id}_{meta['id'].rsplit(':', 1)[-1]}".lower())[:40]
    try:
        sandbox_db(db, ops_by_scope)
        metric = pass_times(provider_dir, db, bench, login, between_passes(db, ops_by_scope))
    finally:
        subprocess.run(["dropdb", "--if-exists", db], capture_output=True)
    rule = contract(provider_dir)
    served = service_cases(provider_dir, slot, bench, login, db[:36] + "_svc")
    total = {"passed": rule["passed"] + (served or {}).get("passed", 0), "total": rule["total"] + (served or {}).get("total", 0),
             "rule": rule, **({"service": served} if served is not None else {})}
    return {"provider": meta["id"], "slot": slot, "dataset": exp_id,
            "inputs": sum(len(v) for v in ops_by_scope.values()), "contract": total,
            "metric": {"name": bench["metric"], "better": bench.get("better", "lower"), **metric}}


def experiment(exp_dir: Path, record, private: Path) -> list[Path]:
    """Measure the candidate and the incumbent from copies in `private` (a directory only this process
    writes); write their run files there and return them."""
    spec = yaml.safe_load((exp_dir / "experiment.yaml").read_text())
    slot = spec["slot"]
    bench = yaml.safe_load((CONTRACT / "slots" / slot / "benchmark.yaml").read_text())
    incumbent = (ROOT / spec["incumbent"]).resolve()
    if not incumbent.is_relative_to(ROOT / "morphogen" / "modules") and not incumbent.is_relative_to(ROOT / "kernel" / "providers"):
        raise ValueError(f"the incumbent {spec['incumbent']} is not one of the repository's providers")
    login = login_of(incumbent)
    if login is None:
        raise ValueError(f"{spec['incumbent']} declares no login of its own (provider.yaml role, login)")
    ops = inputs(record, bench["inputs"])
    results = {}
    for role, d in (("incumbent", incumbent), ("candidate", exp_dir / spec["candidate"])):
        copy = private / role / d.name
        shutil.copytree(d, copy, ignore=shutil.ignore_patterns("__pycache__", "runs"), symlinks=True)
        results[role] = measure(copy, slot, record, exp_dir.name, bench, ops, login)
    files = []                                           # written once no provider code runs any more
    for role, result in results.items():
        f = private / f"{exp_dir.name}-{role}.json"
        f.write_text(json.dumps({**result, "role": role, "request": spec.get("request")}, indent=2) + "\n")
        files.append(f)
    return files
