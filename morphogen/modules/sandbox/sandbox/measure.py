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
     submits (R5-23); cases passed of total, both counted together, each set counting all of its case
     files even when fewer ran;
  2. creates a sandbox database, installs the kernel and Morphogen's modules, and copies into it the
     claims the slot's benchmark names (morphogen/contract/slots/<slot>/benchmark.yaml), read from the
     record under the sandbox's own clearance, each referencing the claim it copies;
  3. times full passes of the provider there from this process (driver.py runs its benchmark entry,
     `<package>.__main__.one_pass(conn)`, one pass per signal), adding one new window of input before
     each pass, as production does (every third one an outlier), and the validator's verdicts between
     passes; the mean of the timed passes is the metric. What the passes submitted and the kernel applied
     is kept (the slot's service.py `outputs`); then the database is dropped;
  4. requires the candidate's outputs on the benchmark to equal the incumbent's on the same inputs: one
     more contract case (`agreement`; the incumbent agrees with itself);
  5. writes `<experiment>-<incumbent|candidate>.json` in the private directory ({"provider", "slot",
     "dataset", "contract", "metric"}) for the evaluator, which records it as DQV measurements.

Provider code runs with none of this process's credentials: the contract with no database settings at
all, the service as the incumbent's own login (provider.yaml `role`, `login`; morphogen.logins), which a
candidate shares; an incumbent that declares no login is not measured. The metric is this process's clock,
not the provider's telemetry (R5-23); provider code that runs in the driver's process could still cheat it
(a pass that returns before its work is done), which the person reviewing the candidate's code sees.
After each provider's runs the sandbox ends everything that provider started (the driver's session, any
process carrying its run marker, the login's database sessions) before it drops the databases, so no
provider code is left running when the run files are written. All of this is same-OS-user isolation:
it holds against a candidate that does not reach past its own process group and environment, not
against one that reads the cluster with the trust a local socket gives (R5-23 (f); T8).

The sandbox writes no claims itself: the evaluator records the scores, and this module's run records
what it did. Creating databases needs a superuser login for the sandbox's cluster (the PG* environment);
the record is read through DATABASE_URL as KK_ROLE.
"""
from __future__ import annotations

import contextlib
import importlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import select
import sys
import tempfile
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


def slot_code(slot: str):
    """The slot's service.py, or None."""
    f = CONTRACT / "slots" / slot / "service.py"
    if not f.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"service_{slot}", f)
    svc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(svc)
    return svc


def end_run(db: str, login: tuple[str, str], marker: str, under: Path) -> None:
    """End whatever one provider's runs left behind: processes carrying its run marker or working under its
    copy, and its login's sessions on the database."""
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            mine = f"KK_SANDBOX_RUN={marker}".encode() in (proc / "environ").read_bytes().split(b"\0")
            mine = mine or Path(os.readlink(proc / "cwd")).is_relative_to(under)
        except OSError:
            continue
        if mine:
            try:
                os.kill(int(proc.name), signal.SIGKILL)
            except OSError:
                pass
    with connect(url=f"dbname={db}") as su:
        su.execute("select pg_terminate_backend(pid) from pg_stat_activity where usename = %s and pid <> pg_backend_pid()",
                   (login[1],))


def drop(db: str) -> None:
    subprocess.run(["dropdb", "--if-exists", "--force", db], check=True, capture_output=True)


def pass_times(provider_dir: Path, db: str, bench: dict, login: tuple[str, str], between, marker: str) -> dict:
    """Time the provider's passes from this process (R5-23): its `<package>.__main__.<entry>(conn)`, run by
    driver.py as `login` (role, login) on the sandbox database, in a session of its own. `between()`
    changes the record before each pass, as production does, so a pass cannot skip its work because nothing
    changed. The first `warmup` passes are not counted. Returns {"passes", "mean", "times"} or {"error"}."""
    meta = yaml.safe_load((provider_dir / "provider.yaml").read_text())
    m = re.fullmatch(r"python3 -m ([a-z_][a-z0-9_]*)", str(meta.get("service", "")))
    if not m:
        return {"error": "the service must be python3 -m <package>"}
    env = login_env(f"dbname={db}", *login, {"PYTHONPATH": pythonpath(provider_dir), "PYTHONDONTWRITEBYTECODE": "1",
                                              "KK_SANDBOX_RUN": marker})
    limit = float(bench.get("pass_timeout", 60))
    with tempfile.TemporaryFile() as log:                # stderr goes to a file: a full pipe would stall a pass
        p = subprocess.Popen([sys.executable, str(DRIVER), m.group(1), bench.get("entry", "one_pass")], cwd=provider_dir,
                             env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, start_new_session=True)
        buf = [b""]

        def line() -> str:                               # the raw descriptor: nothing waits in a reader's buffer
            deadline = time.monotonic() + limit
            while b"\n" not in buf[0]:
                left = deadline - time.monotonic()
                if left <= 0 or not select.select([p.stdout], [], [], left)[0]:
                    return "timeout"
                chunk = os.read(p.stdout.fileno(), 4096)
                if not chunk:
                    return "exited"
                buf[0] += chunk
            got, buf[0] = buf[0].split(b"\n", 1)
            return got.decode(errors="replace").strip()
        times, err = [], None
        try:
            if (got := line()) != "ready":
                err = f"the driver did not start ({got})"
            for i in range(int(bench.get("warmup", 1)) + int(bench.get("passes", 5)) if err is None else 0):
                between()
                t0 = time.perf_counter()
                p.stdin.write(b"pass\n")
                p.stdin.flush()
                got = line()
                dt = time.perf_counter() - t0
                if got != "done":
                    err = f"pass {i + 1}: {got}"
                    break
                if i >= int(bench.get("warmup", 1)):
                    times.append(round(dt, 6))
        finally:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            p.wait()
            log.seek(0)
            stderr = log.read().decode(errors="replace")
    if err:
        return {"error": (err + " " + stderr.strip()[-300:]).strip()}
    return {"passes": len(times), "mean": round(sum(times) / len(times), 6), "times": times}


def validate(db: str) -> None:
    """The validator's verdicts on what was submitted, so valid auto-lane change sets are applied, as in
    production (kernel/providers/validator-shacl)."""
    d = str(ROOT / "kernel" / "providers" / "validator-shacl")
    if d not in sys.path:
        sys.path.insert(0, d)
    with connect("kkm_validator", f"dbname={db}") as val, contextlib.redirect_stdout(sys.stderr):
        importlib.import_module("validator.__main__").drain(val)


def applied(db: str, agent: str, after: set) -> list[list[dict]]:
    """The ops of the change sets attributed to `agent` that the kernel applied, other than those in `after`."""
    with connect(url=f"dbname={db}") as su:
        return [ops for cid, ops in su.execute("select id, ops from kernel.change_set where status = 'applied' "
                                               "and attributed_to = %s order by submitted_at", (agent,)).fetchall()
                if cid not in after]


def names(db: str) -> dict[str, str]:
    """claim id -> a name that does not depend on the database: its references and its window."""
    with connect(url=f"dbname={db}") as su:
        return {cid: f"{refs}@{vf.isoformat() if vf else ''}" for cid, refs, vf in su.execute(
            """select c.id::text, string_agg(r.source_uri, ' ' order by r.source_uri), c.valid_from
               from kernel.claim c join kernel.claim_reference r on r.claim_id = c.id group by c.id, c.valid_from""")}


def between_passes(db: str, ops_by_scope: dict[str, list[dict]]):
    """A function adding, each time it is called, one new window of the newest copied input series (every
    third one four times the seed's value), then the validator's verdicts: the change production sees
    between passes. Each window is attributed to the sandbox and cites the claim it copies."""
    seed = max((op for ops in ops_by_scope.values() for op in ops if op.get("valid_from") and op.get("valid_to")),
               key=lambda op: datetime.fromisoformat(op["valid_from"]), default=None)
    scope = next((sc for sc, ops in ops_by_scope.items() if seed in ops), None)
    count = [0]

    def add() -> None:
        validate(db)
        if seed is None:
            return
        count[0] += 1
        start, end = datetime.fromisoformat(seed["valid_from"]), datetime.fromisoformat(seed["valid_to"])
        shift = (end - start) * count[0]
        obj = seed["object"]
        if count[0] % 3 == 0 and isinstance(obj.get("value"), dict):
            try:
                obj = {"value": {**obj["value"], "@value": round(float(obj["value"]["@value"]) * 4, 6)}}
            except (TypeError, ValueError):
                pass
        op = {**seed, "object": obj, "valid_from": (start + shift).isoformat(), "valid_to": (end + shift).isoformat()}
        with connect(url=f"dbname={db}") as su:
            su.execute("set role kk_owner")
            su.execute("select kernel.install_ops(%s, %s, %s, 'urn:kk:agent:sandbox', %s)",
                       (f"sandbox:between:{count[0]}", scope, Jsonb([op]), MODULE))
    return add


MODULE = "urn:kk:module:sandbox"


def sandbox_db(name: str, ops_by_scope: dict[str, list[dict]]) -> None:
    sys.path.insert(0, str(ROOT / "morphogen" / "modules"))
    install = importlib.import_module("install")         # morphogen/modules/install.py
    drop(name)
    install.install(name, install.modules())
    with connect(url=f"dbname={name}") as su:
        su.execute("set role kk_owner")
        for scope, ops in sorted(ops_by_scope.items()):
            if su.execute("select 1 from kernel.scope where iri = %s", (scope,)).fetchone() is None:
                su.execute("insert into kernel.scope(iri, label) values (%s, %s)", (scope, scope))
            su.execute("select kernel.install_ops(%s, %s, %s)", (f"sandbox:inputs:{scope}", scope, Jsonb(ops)))


def service_cases(provider_dir: Path, slot: str, bench: dict, login: tuple[str, str], db: str, agent: str,
                  marker: str) -> dict | None:
    """The slot's service cases (morphogen/contract/slots/<slot>/service.py), if it has them: every case
    loaded into a fresh database, one pass of the provider as `login`, the change sets it submitted that
    the kernel applied, attributed to `agent`, judged by the slot's code. {"passed", "total", "failed"};
    None when the slot has no service cases."""
    svc = slot_code(slot)
    if svc is None:
        return None
    ops, expected = svc.ops(sorted((CONTRACT / "slots" / slot / "cases").glob("*.yaml")))
    try:
        sandbox_db(db, {"urn:kk:scope:default": ops})
        with connect(url=f"dbname={db}") as su:
            ids = {cid: got for cid, uri in su.execute("select claim_id::text, source_uri from kernel.claim_reference "
                                                       "where source_uri like 'urn:kk:case:%%'").fetchall()
                   if (got := svc.ref(uri))}
            before = {r[0] for r in su.execute("select id from kernel.change_set").fetchall()}
        ran = pass_times(provider_dir, db, {**bench, "warmup": 0, "passes": 1}, login, lambda: None, marker)
        end_run(db, login, marker, provider_dir.parent)
        if "error" in ran:
            return {"passed": 0, "total": len(expected), "failed": ["(the pass failed)"], "error": ran["error"]}
        validate(db)
        sets = applied(db, agent, before)
    finally:
        drop(db)
    return svc.judge(sets, ids, expected)


def measure(provider_dir: Path, slot: str, record, exp_id: str, bench: dict, ops_by_scope: dict,
            login: tuple[str, str], agent: str) -> dict:
    """The provider's contract (the slot's rule cases, plus its service cases when it has them, counted
    together) and its benchmark, with what its benchmark passes submitted (`outputs`, compared by
    `experiment`)."""
    meta = yaml.safe_load((provider_dir / "provider.yaml").read_text())
    db = "kk_sbx_" + re.sub(r"[^a-z0-9]", "_", f"{exp_id}_{meta['id'].rsplit(':', 1)[-1]}".lower())[:40]
    marker = secrets.token_hex(8)
    svc = slot_code(slot)
    outputs = None
    try:
        sandbox_db(db, ops_by_scope)
        metric = pass_times(provider_dir, db, bench, login, between_passes(db, ops_by_scope), marker)
        end_run(db, login, marker, provider_dir.parent)
        if svc is not None and "error" not in metric:
            validate(db)
            outputs = svc.outputs(applied(db, agent, set()), names(db))
    finally:
        drop(db)
    rule = contract(provider_dir)
    served = service_cases(provider_dir, slot, bench, login, db[:36] + "_svc", agent, marker)
    end_run("postgres", login, marker, provider_dir.parent)
    n = len(list((CONTRACT / "slots" / slot / "cases").glob("*.yaml")))
    rule["total"] = max(rule["total"], n)                # a case that did not run counts as failed
    if served is not None:
        served["total"] = max(served["total"], n)
    total = {"passed": rule["passed"] + (served or {}).get("passed", 0), "total": rule["total"] + (served or {}).get("total", 0),
             "rule": rule, **({"service": served} if served is not None else {})}
    return {"provider": meta["id"], "slot": slot, "dataset": exp_id,
            "inputs": sum(len(v) for v in ops_by_scope.values()), "contract": total,
            "metric": {"name": bench["metric"], "better": bench.get("better", "lower"), **metric},
            "outputs": outputs}


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
    agent = (yaml.safe_load((incumbent / "provider.yaml").read_text()) or {}).get("agent")
    if slot_code(slot) is not None and not agent:
        raise ValueError(f"{spec['incumbent']} declares no agent (provider.yaml agent): its outputs cannot be judged")
    ops = inputs(record, bench["inputs"])
    results = {}
    work = private / "work"
    for role, d in (("incumbent", incumbent), ("candidate", exp_dir / spec["candidate"])):
        copy = work / role / d.name
        shutil.copytree(d, copy, ignore=shutil.ignore_patterns("__pycache__", "runs"), symlinks=True)
        results[role] = measure(copy, slot, record, exp_dir.name, bench, ops, login, agent)
    shutil.rmtree(work)
    # The candidate must submit what the incumbent submits on the same benchmark inputs.
    inc = results["incumbent"].pop("outputs")
    cand = results["candidate"].pop("outputs")
    if inc is not None:
        for role, agrees in (("incumbent", True), ("candidate", cand == inc)):
            c = results[role]["contract"]
            c["agreement"] = {"passed": int(agrees), "total": 1, "outputs": len(inc if role == "incumbent" else cand or [])}
            c["passed"] += int(agrees)
            c["total"] += 1
    out = private / "runs"                               # a fresh directory, made once no provider code runs
    out.mkdir()
    files = []
    for role, result in results.items():
        f = out / f"{exp_dir.name}-{role}.json"
        f.write_text(json.dumps({**result, "role": role, "request": spec.get("request")}, indent=2) + "\n")
        files.append(f)
    return files
