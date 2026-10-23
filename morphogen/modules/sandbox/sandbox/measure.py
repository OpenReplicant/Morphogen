"""One experiment: a candidate provider and the slot's incumbent, each checked against the slot's
contract and measured on a copy of the record (R5-21).

An experiment is a directory `intent/experiments/<id>/` with `experiment.yaml`:

  slot: analyser
  incumbent: morphogen/modules/anomaly          # relative to the repository
  candidate: anomaly-recent                     # a provider directory inside the experiment
  request: urn:kk:request:...                   # what asked for it (optional)

For each of the two providers it
  1. runs the slot's contract (kernel/contract/run.py on the provider's directory): cases passed of total;
  2. creates a sandbox database, installs the kernel and Morphogen's modules, and copies into it the
     claims the slot's benchmark names (morphogen/contract/slots/<slot>/benchmark.yaml), read from the
     record under the sandbox's own clearance, each referencing the claim it copies;
  3. runs the provider's service there for the benchmark's seconds, with OpenTelemetry pointed at a
     receiver in this process, and takes the mean of the benchmark's metric; then drops the database;
  4. writes `runs/<provider>.json` in the experiment ({"provider", "slot", "dataset", "contract",
     "metric"}) for the evaluator, which records it as DQV measurements.

The sandbox writes no claims itself: the evaluator records the scores, and this module's run records
what it did. Creating databases needs a superuser login for the sandbox's cluster (the PG* environment);
the record is read through DATABASE_URL as KK_ROLE.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml
from psycopg.types.json import Jsonb

from kk.lib import connect

ROOT = Path(__file__).resolve().parents[4]
CONTRACT = ROOT / "morphogen" / "contract"
PASSED = re.compile(r"^\S+: (\d+)/(\d+) contract cases passed$", re.M)


def contract(provider_dir: Path) -> dict:
    """The slot contract on one provider: {"passed", "total"} (0 of 0 when the slot has none)."""
    out = subprocess.run([sys.executable, str(ROOT / "kernel" / "contract" / "run.py"),
                          "--blueprint", str(ROOT / "kernel" / "blueprint" / "slots.yaml"),
                          "--blueprint", str(ROOT / "morphogen" / "distribution.yaml"),
                          "--providers", str(provider_dir.parent), provider_dir.name],
                         capture_output=True, text=True, env={**os.environ, "PYTHONPATH": pythonpath(provider_dir)})
    m = PASSED.search(out.stdout)
    return {"passed": int(m.group(1)), "total": int(m.group(2))} if m else {"passed": 0, "total": 0}


def pythonpath(d: Path) -> str:
    return os.pathsep.join(filter(None, [str(d), str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "src"),
                                         os.environ.get("PYTHONPATH")]))


def inputs(record, predicates: list[str]) -> dict[str, list[dict]]:
    """scope -> add_claim ops copying the current claims with these predicates that the role may read."""
    rows = record.execute("""select id, subject, predicate, object_entity, object_value, qualifiers, valid_from,
                                    valid_to, evidence_type, scope from api.claims
                             where predicate = any(%s) and status <> 'deprecated' and redacted_at is null""",
                          (predicates,)).fetchall()
    out: dict[str, list[dict]] = {}
    for cid, s, p, oe, ov, q, vf, vt, ev, scope in rows:
        op = {"op": "add_claim", "subject": s, "predicate": p,
              "object": {"entity": oe} if oe is not None else {"value": ov}, "qualifiers": q or {},
              "evidence_type": "deterministic" if ev == "extracted" else ev,
              "references": [{"source_uri": f"urn:kk:claim:{cid}"}]}
        if vf:
            op["valid_from"] = vf.isoformat()
        if vt:
            op["valid_to"] = vt.isoformat()
        out.setdefault(scope, []).append(op)
    return out


class Collector:
    """An OTLP/HTTP JSON receiver for one metric: the sum and count of its histogram points."""

    def __init__(self, metric: str):
        self.metric, self.total, self.count = metric, 0.0, 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                for rm in body.get("resourceMetrics", []):
                    for sm in rm.get("scopeMetrics", []):
                        for m in sm.get("metrics", []):
                            if m.get("name") == outer.metric:
                                for p in m.get("histogram", {}).get("dataPoints", []):
                                    outer.total += float(p.get("sum", 0))
                                    outer.count += int(p.get("count", 0))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def close(self) -> None:
        self.server.shutdown()


def run_service(provider_dir: Path, db: str, bench: dict) -> dict:
    """Run the provider's service on the sandbox database; the mean of the benchmark metric."""
    meta = yaml.safe_load((provider_dir / "provider.yaml").read_text())
    cmd = shlex.split(meta["service"])
    if cmd[0] == "python3":
        cmd[0] = sys.executable
    col = Collector(bench["metric"])
    env = {**os.environ, **{k: str(v) for k, v in (bench.get("env") or {}).items()},
           "DATABASE_URL": f"dbname={db}", "PYTHONPATH": pythonpath(provider_dir),
           "OTEL_EXPORTER_OTLP_ENDPOINT": col.url, "OTEL_METRIC_EXPORT_INTERVAL": "500", "OTEL_SERVICE_NAME": meta["id"]}
    env.pop("OTEL_EXPORTER_OTLP_HEADERS", None)
    p = subprocess.Popen(cmd, cwd=provider_dir, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        time.sleep(float(os.environ.get("KK_BENCH_SECONDS") or bench.get("seconds", 8)))
    finally:
        p.terminate()
        try:
            _, err = p.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
            _, err = p.communicate()
    time.sleep(0.6)                                      # the last export
    col.close()
    out = {"steps": col.count, "mean": round(col.total / col.count, 6) if col.count else None}
    if not col.count:
        out["error"] = (err or "").strip()[-300:] or "no measurements"
    return out


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


def measure(provider_dir: Path, slot: str, record, exp_id: str, bench: dict, ops_by_scope: dict) -> dict:
    meta = yaml.safe_load((provider_dir / "provider.yaml").read_text())
    db = "kk_sbx_" + re.sub(r"[^a-z0-9]", "_", f"{exp_id}_{meta['id'].rsplit(':', 1)[-1]}".lower())[:40]
    sandbox_db(db, ops_by_scope)
    try:
        metric = run_service(provider_dir, db, bench)
    finally:
        subprocess.run(["dropdb", "--if-exists", db], capture_output=True)
    return {"provider": meta["id"], "slot": slot, "dataset": exp_id,
            "inputs": sum(len(v) for v in ops_by_scope.values()), "contract": contract(provider_dir),
            "metric": {"name": bench["metric"], "better": bench.get("better", "lower"), **metric}}


def experiment(exp_dir: Path, record) -> list[Path]:
    """Measure the candidate and the incumbent; write and return their run files."""
    spec = yaml.safe_load((exp_dir / "experiment.yaml").read_text())
    slot = spec["slot"]
    bench = yaml.safe_load((CONTRACT / "slots" / slot / "benchmark.yaml").read_text())
    ops = inputs(record, bench["inputs"])
    runs = exp_dir / "runs"
    runs.mkdir(exist_ok=True)
    files = []
    for role, d in (("incumbent", ROOT / spec["incumbent"]), ("candidate", exp_dir / spec["candidate"])):
        result = measure(d.resolve(), slot, record, exp_dir.name, bench, ops)
        f = runs / f"{exp_dir.name}-{role}.json"
        f.write_text(json.dumps({**result, "role": role, "request": spec.get("request")}, indent=2) + "\n")
        files.append(f)
    return files
