"""Sandbox: a candidate analyser and the incumbent are checked against the analyser contract and measured
on a copy of a record holding 4,500 observations; the evaluator records both, each linked to its provider.
A broken candidate fails the contract.

  PGHOST=... PGUSER=<superuser> python3 tests/test_sandbox.py   (about half a minute)
"""
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "modules"),
                str(ROOT / "kernel" / "providers" / "validator-shacl")]
import importlib  # noqa: E402

from psycopg.types.json import Jsonb  # noqa: E402

from kk.lib import connect  # noqa: E402
from sandbox.measure import contract  # noqa: E402

install = importlib.import_module("install")
validator = importlib.import_module("validator.__main__")
DB = "kk_sandbox_test"
SOSA = "http://www.w3.org/ns/sosa/"
DQV = "http://www.w3.org/ns/dqv#"
XSD = "http://www.w3.org/2001/XMLSchema#"


def check(cond, msg):
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def observations(targets: int, windows: int) -> list[dict]:
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return [{"op": "add_claim", "subject": f"urn:kk:provider:p{t}", "predicate": SOSA + "hasSimpleResult",
             "object": {"value": {"@value": 0.01 + 0.001 * (w % 3), "@type": XSD + "decimal"}},
             "qualifiers": {SOSA + "observedProperty": "urn:kk:property:step-seconds-mean"},
             "valid_from": (t0 + timedelta(minutes=w)).isoformat(), "valid_to": (t0 + timedelta(minutes=w + 1)).isoformat(),
             "evidence_type": "observed", "references": [{"source_uri": "urn:kk:test:sandbox"}]}
            for t in range(targets) for w in range(windows)]


PROBE = """    import pathlib
    pathlib.Path({path!r}).write_text(" ".join([
        conn.execute("select session_user").fetchone()[0],
        ",".join(sorted(k for k in os.environ if k.startswith("PG") or k == "OTEL_EXPORTER_OTLP_HEADERS")) or "-",
        str(any(pathlib.Path("../..").rglob("*.json")))]))
"""


def main() -> None:
    subprocess.run(["dropdb", "--if-exists", DB], check=True)
    os.environ.setdefault("KK_LOGIN_PASSWORD", secrets.token_hex(16))   # the modules' own logins (R5-22)
    install.install(DB, install.modules())
    url = f"dbname={DB}"
    with connect(url=url) as su:
        su.execute("set role kk_owner")
        su.execute("select kernel.install_ops('test:observations', 'urn:kk:scope:default', %s)", (Jsonb(observations(30, 150)),))

    tmp = Path(tempfile.mkdtemp())
    exp = tmp / "exp1"
    exp.mkdir()
    shutil.copytree(ROOT / "morphogen" / "tests" / "fixtures" / "analyser" / "anomaly-recent", exp / "anomaly-recent",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (exp / "experiment.yaml").write_text("slot: analyser\nincumbent: morphogen/modules/anomaly\ncandidate: anomaly-recent\n")

    # A probe in the candidate: who it connects as, what credentials it was given, and whether it can
    # reach a run file.
    probe = tmp / "probe.txt"
    m = exp / "anomaly-recent" / "anomaly_recent" / "__main__.py"
    hook = '    conn = connect(os.environ.get("KK_ROLE", "kkm_anomaly"))\n'
    m.write_text(m.read_text().replace(hook, hook + PROBE.format(path=str(probe)), 1))
    broken = tmp / "broken" / "anomaly-recent"
    shutil.copytree(exp / "anomaly-recent", broken)
    d = broken / "anomaly_recent" / "detect.py"
    d.write_text(d.read_text().replace("if (node, prop) in limit and v > limit[(node, prop)][0]:", "if False:"))
    got = contract(broken)
    check(got["total"] == 11 and got["passed"] < 11, f"a candidate that ignores limits fails the analyser contract ({got['passed']}/11)")

    env = {**os.environ, "DATABASE_URL": url, "KK_BENCH_SECONDS": "6",
           "PYTHONPATH": os.pathsep.join([str(HERE), str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "src")]),
           "KK_ARTIFACTS": str(tmp / "artifacts")}
    out = subprocess.run([sys.executable, "-m", "sandbox", str(exp)], cwd=HERE, env=env, capture_output=True, text=True)
    check(out.returncode == 0, "the sandbox measures the experiment: " + (out.stderr or out.stdout)[-600:].strip())
    with connect("kkm_validator", url) as val:
        validator.drain(val)
    with connect("kkm_sandbox", url) as reader:
        q = lambda sql, *a: reader.execute(sql, a).fetchall()
        runs = dict(q("""select s.subject, s.object_entity from api.claims s where s.predicate = 'http://purl.org/dc/terms/subject'
                         and s.subject like 'urn:kk:eval:sandbox-analyser:%%'"""))
        check(set(runs.values()) == {"urn:kk:provider:anomaly", "urn:kk:provider:anomaly-recent"},
              "the evaluator records both runs, each linked to the provider it measured")
        value = lambda provider, metric: next(float(v) for s, v in q(
            f"""select subject, object_value->>'@value' from api.claims where predicate = %s
                and qualifiers->>%s = %s and subject = any(%s)""", DQV + "value", DQV + "isMeasurementOf",
            f"urn:kk:metric:sandbox-analyser:{metric}", [k for k, p in runs.items() if p == provider]))
        for p in ("urn:kk:provider:anomaly", "urn:kk:provider:anomaly-recent"):
            check(value(p, "contract.passed") == value(p, "contract.total") == 11, f"{p.rsplit(':', 1)[-1]} passes the analyser contract (11/11)")
        inc, cand = value("urn:kk:provider:anomaly", "metric.mean"), value("urn:kk:provider:anomaly-recent", "metric.mean")
        check(cand < inc, f"on a copy of the record the candidate's step is faster ({cand:.3f} s against {inc:.3f} s)")
        check(value("urn:kk:provider:anomaly", "inputs") == 4500, "the sandbox copied the record's 4,500 observations")
        check(not q("select 1 from api.claims where attributed_to = 'urn:kk:agent:sandbox'"), "the sandbox wrote no claims")
    who, creds, sees = probe.read_text().split()
    check(who == "kkm_anomaly_login" and set(creds.split(",")) <= {"-", "PGHOST", "PGPORT"} and sees == "False",
          f"the candidate runs as the incumbent's own login ({who}), with no other credentials ({creds}), "
          "and cannot see the run files")
    left = subprocess.run(["psql", "-d", "postgres", "-qAtc", "select count(*) from pg_database where datname like 'kk_sbx_%'"],
                          capture_output=True, text=True).stdout.strip()
    check(left == "0", "the sandbox databases are dropped")
    shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
