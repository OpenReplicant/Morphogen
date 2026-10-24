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
import yaml  # noqa: E402
from sandbox.measure import contract, experiment, service_cases  # noqa: E402

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
    hook = 'def one_pass(conn, seen: dict | None = None) -> dict:\n'
    m.write_text(m.read_text().replace(hook, hook + PROBE.format(path=str(probe)), 1))
    broken = tmp / "broken" / "anomaly-recent"
    shutil.copytree(exp / "anomaly-recent", broken)
    d = broken / "anomaly_recent" / "detect.py"
    d.write_text(d.read_text().replace("if (node, prop) in limit and v > limit[(node, prop)][0]:", "if False:"))
    got = contract(broken)
    N = len(list((ROOT / "morphogen" / "contract" / "slots" / "analyser" / "cases").glob("*.yaml")))
    check(got["total"] == N and got["passed"] < N, f"a candidate that ignores limits fails the analyser contract ({got['passed']}/{N})")

    # A candidate whose rule is right but whose reading of the record is not: it reads only providers'
    # observations. The rule cases pass; the service cases (one real pass on every case) do not.
    narrow = tmp / "narrow" / "anomaly-recent"
    shutil.copytree(ROOT / "morphogen" / "tests" / "fixtures" / "analyser" / "anomaly-recent", narrow,
                    ignore=shutil.ignore_patterns("__pycache__"))
    n = narrow / "anomaly_recent" / "__main__.py"
    n.write_text(n.read_text().replace("and c.evidence_type = 'observed') x",
                                       "and c.evidence_type = 'observed' and c.subject like 'urn:kk:provider:%%') x"))
    bench = yaml.safe_load((ROOT / "morphogen" / "contract" / "slots" / "analyser" / "benchmark.yaml").read_text())
    served = service_cases(narrow, "analyser", bench, ("kkm_anomaly", "kkm_anomaly_login"), "kk_sbx_test_narrow",
                           "urn:kk:agent:anomaly", secrets.token_hex(8))
    check(contract(narrow)["passed"] == N and served["total"] == N and served["passed"] < N,
          f"a candidate that reads only some of the record passes the rule cases and fails the service cases ({served['passed']}/{N})")

    # A candidate that reads the record correctly only when it sees case data, and leaves a process behind
    # in a session of its own. The rule and service cases pass; its benchmark outputs differ from the
    # incumbent's, and nothing it started outlives the run.
    cheat_exp = tmp / "exp2"
    shutil.copytree(ROOT / "morphogen" / "tests" / "fixtures" / "analyser" / "anomaly-recent", cheat_exp / "anomaly-recent",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (cheat_exp / "experiment.yaml").write_text("slot: analyser\nincumbent: morphogen/modules/anomaly\ncandidate: anomaly-recent\n")
    left_pid = tmp / "left.pid"
    c = cheat_exp / "anomaly-recent" / "anomaly_recent" / "__main__.py"
    c.write_text(c.read_text().replace("        found = anomalies(obs, limits)\n", f"""        found = anomalies(obs, limits)
        found = [a for a in found if "-c" in a["target"]]
        import subprocess
        if not pathlib.Path({str(left_pid)!r}).exists():
            pathlib.Path({str(left_pid)!r}).write_text(str(subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(600)"], start_new_session=True).pid))
""", 1).replace("import sys\n", "import pathlib\nimport sys\n", 1))
    priv = tmp / "priv"
    priv.mkdir()
    old_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    with connect("kkm_sandbox", url) as record:
        runs = {f.stem.rsplit("-", 1)[-1]: yaml.safe_load(f.read_text())["contract"] for f in experiment(cheat_exp, record, priv)}
    os.environ.pop("DATABASE_URL") if old_url is None else os.environ.update(DATABASE_URL=old_url)
    cc = runs["candidate"]
    check(cc["rule"]["passed"] == N and cc["service"]["passed"] == N and cc["agreement"]["passed"] == 0
          and cc["passed"] < cc["total"],
          f"a candidate that reads the record one way for the cases and another for the benchmark passes {N}+{N} "
          f"cases and fails the agreement with the incumbent ({cc['agreement']['outputs']} outputs against "
          f"{runs['incumbent']['agreement']['outputs']})")
    pid = int(left_pid.read_text())
    check(not Path(f"/proc/{pid}").exists() or "zombie" in Path(f"/proc/{pid}/status").read_text().lower(),
          "a process the candidate started in a session of its own does not outlive its run")

    env = {**os.environ, "DATABASE_URL": url,
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
            check(value(p, "contract.passed") == value(p, "contract.total") == 2 * N + 1 and value(p, "contract.service.passed") == N,
                  f"{p.rsplit(':', 1)[-1]} passes the analyser contract: {N} rule cases, {N} service cases and "
                  "the same outputs as the incumbent on the benchmark")
        inc, cand = value("urn:kk:provider:anomaly", "metric.mean"), value("urn:kk:provider:anomaly-recent", "metric.mean")
        check(cand < inc, f"on a copy of the record, timed by the sandbox, the candidate's full pass is faster ({cand:.3f} s against {inc:.3f} s)")
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
