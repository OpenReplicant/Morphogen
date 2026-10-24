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
from morphogen import confine  # noqa: E402
from sandbox.measure import contract, drop_login, experiment, fresh_login, sandbox_cluster, service_cases  # noqa: E402

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


PROBE = """    global _PROBED
    if not globals().get("_PROBED"):         # once per process: the probe is slow, and the passes are timed
        _PROBED = True
        import pathlib, pwd, psycopg
        def _try(f):
            try:
                f()
                return "open"
            except Exception:
                return "closed"
        pathlib.Path({path!r}).write_text(" ".join([
            conn.execute("select session_user").fetchone()[0],
            ",".join(sorted(k for k in os.environ if k.startswith("PG") or k == "OTEL_EXPORTER_OTLP_HEADERS")) or "-",
            str(any(pathlib.Path("../..").rglob("*.json"))),
            pwd.getpwuid(os.getuid()).pw_name,
            _try(lambda: pathlib.Path(f"/proc/{{os.getppid()}}/environ").read_bytes()),
            _try(lambda: psycopg.connect(dbname="postgres", user="postgres", connect_timeout=5).close()),
            _try(lambda: psycopg.connect(os.environ["DATABASE_URL"], dbname={record!r}, host={rhost!r}, port={rport!r},
                                         connect_timeout=5).close())]))
"""


def confined(provider: Path, db: str) -> tuple[dict, dict]:
    """The rule and service cases on one provider directory, run as measure() runs them."""
    bench = yaml.safe_load((ROOT / "morphogen" / "contract" / "slots" / "analyser" / "benchmark.yaml").read_text())
    with sandbox_cluster(), confine.workspace() as ws, confine.lease(allow=[confine.where()]) as run, run.home() as h:
        (ws / "p").mkdir(mode=0o755)
        copy = ws / "p" / provider.name
        confine.copy_tree(provider, copy)
        login = fresh_login("kkm_anomaly")
        try:
            return contract(copy, run, h), service_cases(copy, "analyser", bench, login, db, "urn:kk:agent:anomaly", run, h)
        finally:
            drop_login(login)


def main() -> None:
    subprocess.run(["dropdb", "--if-exists", DB], check=True)
    os.environ.setdefault("KK_LOGIN_PASSWORD", secrets.token_hex(16))   # the modules' own logins (R5-22)
    install.install(DB, install.modules())
    url = f"dbname={DB}"
    with connect(url=url) as su:
        su.execute("set role kk_owner")
        su.execute("select kernel.install_ops('test:observations', 'urn:kk:scope:default', %s)", (Jsonb(observations(30, 150)),))

    tmp = Path(tempfile.mkdtemp())
    drop = tmp / "drop"                                  # the one place the confined probes may write
    drop.mkdir()
    exp = tmp / "exp1"
    exp.mkdir()
    shutil.copytree(ROOT / "morphogen" / "tests" / "fixtures" / "analyser" / "anomaly-recent", exp / "anomaly-recent",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (exp / "experiment.yaml").write_text("slot: analyser\nincumbent: morphogen/modules/anomaly\ncandidate: anomaly-recent\n")

    # A probe in the candidate: who it connects as, what credentials it was given, and whether it can
    # reach a run file.
    probe = drop / "probe.txt"
    m = exp / "anomaly-recent" / "anomaly_recent" / "__main__.py"
    hook = 'def one_pass(conn, seen: dict | None = None) -> dict:\n'
    m.write_text(m.read_text().replace(hook, hook + PROBE.format(path=str(probe), record=DB, rhost=confine.where()[0], rport=confine.where()[1]), 1))
    broken = tmp / "broken" / "anomaly-recent"
    shutil.copytree(exp / "anomaly-recent", broken)
    d = broken / "anomaly_recent" / "detect.py"
    d.write_text(d.read_text().replace("if (node, prop) in limit and v > limit[(node, prop)][0]:", "if False:"))
    tmp.chmod(0o711)
    drop.chmod(0o1777)
    got, _ = confined(broken, "kk_sbx_test_broken")
    N = len(list((ROOT / "morphogen" / "contract" / "slots" / "analyser" / "cases").glob("*.yaml")))
    check(got["total"] == N and got["passed"] < N, f"a candidate that ignores limits fails the analyser contract ({got['passed']}/{N})")

    # A candidate whose rule is right but whose reading of the record is not: it reads only providers'
    # observations. The rule cases pass; the service cases (one real pass on every case) do not.
    narrow = tmp / "narrow" / "anomaly-recent"
    shutil.copytree(ROOT / "morphogen" / "tests" / "fixtures" / "analyser" / "anomaly-recent", narrow,
                    ignore=shutil.ignore_patterns("__pycache__"))
    n = narrow / "anomaly_recent" / "__main__.py"
    n.write_text(n.read_text().replace("and c.evidence_type = 'observed'",
                                       "and c.evidence_type = 'observed' and c.subject like 'urn:kk:provider:%%'"))
    bench = yaml.safe_load((ROOT / "morphogen" / "contract" / "slots" / "analyser" / "benchmark.yaml").read_text())
    narrow_rule, served = confined(narrow, "kk_sbx_test_narrow")
    check(narrow_rule["passed"] == N and served["total"] == N and served["passed"] < N,
          f"a candidate that reads only some of the record passes the rule cases and fails the service cases ({served['passed']}/{N})")

    # A candidate that keeps what it read on its first pass: every rule case passes, and every service case
    # but the one that retracts an observation and supersedes a limit before a second pass.
    cached = tmp / "cached" / "anomaly-recent"
    shutil.copytree(ROOT / "morphogen" / "tests" / "fixtures" / "analyser" / "anomaly-recent", cached,
                    ignore=shutil.ignore_patterns("__pycache__"))
    c = cached / "anomaly_recent" / "__main__.py"
    c.write_text(c.read_text().replace("        found = anomalies(obs, limits, check)\n", """        global _CACHE
        _CACHE = _CACHE or (obs, limits)
        obs, limits = _CACHE
        found = anomalies(obs, limits, check)
""", 1).replace("def one_pass(", "_CACHE = None\n\n\ndef one_pass(", 1))
    cached_rule, served = confined(cached, "kk_sbx_test_cached")
    check(cached_rule["passed"] == N and served["failed"] == ["urn:kk:eval:analyser/retracted-and-superseded"],
          f"a candidate that keeps what it read passes the rule cases and fails the two-pass service case ({served['passed']}/{N})")

    # A candidate that reads the record correctly only when it sees case data, and leaves a process behind
    # in a session of its own. The rule and service cases pass; its benchmark outputs differ from the
    # incumbent's, and nothing it started outlives the run.
    cheat_exp = tmp / "exp2"
    shutil.copytree(ROOT / "morphogen" / "tests" / "fixtures" / "analyser" / "anomaly-recent", cheat_exp / "anomaly-recent",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (cheat_exp / "experiment.yaml").write_text("slot: analyser\nincumbent: morphogen/modules/anomaly\ncandidate: anomaly-recent\n")
    left_pid = drop / "left.pid"
    c = cheat_exp / "anomaly-recent" / "anomaly_recent" / "__main__.py"
    c.write_text(c.read_text().replace("        found = anomalies(obs, limits, check)\n", f"""        found = anomalies(obs, limits, check)
        found = [a for a in found if "-c" in a["target"]]
        import subprocess
        if not pathlib.Path({str(left_pid)!r}).exists():
            pathlib.Path({str(left_pid)!r}).write_text(str(subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(600)"], start_new_session=True).pid))
""", 1).replace("import sys\n", "import pathlib\nimport sys\n", 1))
    priv = tmp / "priv"
    priv.mkdir(mode=0o700)
    old_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    # Provider code is measured only on a cluster of its own (R5-26): not without one, not on the record's.
    sbx = os.environ.pop("KK_SANDBOX_CLUSTER")
    for given, why in ((None, "is not set"), (f"host={confine.where()[0]} port={confine.where()[1]} user={os.environ['PGUSER']} "
                                                       f"password={os.environ.get('PGPASSWORD', '')}", "is the record's cluster")):
        if given:
            os.environ["KK_SANDBOX_CLUSTER"] = given
        try:
            with connect("kkm_sandbox", url) as record:
                experiment(cheat_exp, record, priv)
            check(False, "the sandbox measures on the record's cluster")
        except confine.Unconfined as e:
            check(why in str(e), f"the sandbox refuses to measure when KK_SANDBOX_CLUSTER {why} ({e})")
    os.environ["KK_SANDBOX_CLUSTER"] = sbx
    run_as = os.environ.pop("KK_RUN_AS")
    try:
        with connect("kkm_sandbox", url) as record:
            experiment(cheat_exp, record, priv)
        check(False, "the sandbox runs a candidate without an OS user of its own")
    except confine.Unconfined as e:
        check("KK_RUN_AS" in str(e), f"without an OS user to run it as, the sandbox refuses to run a candidate ({e})")
    finally:
        os.environ["KK_RUN_AS"] = run_as
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

    # The network (R5-26): a confined run reaches the addresses its lease allows and nothing else, loopback
    # included; once the lease ends its user reaches nothing.
    import socket
    ok, no = socket.create_server(("127.0.0.1", 0)), socket.create_server(("127.0.0.1", 0))
    reach = (f"import socket\nfor h, p in [('127.0.0.1', {ok.getsockname()[1]}), ('127.0.0.1', {no.getsockname()[1]}), "
             "('1.1.1.1', 443)]:\n    try:\n        socket.create_connection((h, p), timeout=3).close(); print('open')\n"
             "    except OSError:\n        print('closed')\n")
    try:
        with confine.lease(allow=[("127.0.0.1", ok.getsockname()[1])]) as run:
            got = run.run([sys.executable, "-I", "-c", reach], {"PATH": "/usr/bin:/bin"}, timeout=60, cwd="/").stdout.split()
            check(got == ["open", "closed", "closed"], f"a confined run reaches only the address its lease allows ({got})")
            user = run.user
        rest = subprocess.run([sys.executable, "-I", "-c", reach], user=user.pw_uid, group=user.pw_gid, extra_groups=[],
                              env={"PATH": "/usr/bin:/bin"}, cwd="/", capture_output=True, text=True, timeout=60).stdout.split()
        check(rest == ["closed"] * 3, f"after its lease the run user reaches nothing ({rest})")
    finally:
        ok.close(), no.close()

    # Nothing a run leaves behind runs later: a run user with a cron or at job is refused. And a lease whose
    # network chain is gone (a flushed ruleset) starts nothing.
    spool = tmp / "spool"
    spool.mkdir()
    spools, confine.SPOOLS = confine.SPOOLS, [spool]
    first = confine.pool()[0]
    (spool / first.pw_name).write_text("* * * * * curl ...\n")
    try:
        os.environ["KK_RUN_AS"], pool_was = first.pw_name, os.environ["KK_RUN_AS"]
        try:
            with confine.lease():
                refused = None
        except confine.Unconfined as e:
            refused = str(e)
        check(refused is not None and "scheduled jobs" in refused, "a run user with a cron job is refused")
        (spool / first.pw_name).unlink()
        with confine.lease() as run:
            os.chown(spool, run.user.pw_uid, run.user.pw_gid)
            run.run(["/bin/sh", "-c", f"echo job > {spool}/{first.pw_name}"], {"PATH": "/usr/bin:/bin"}, timeout=30, cwd="/")
            planted = (spool / first.pw_name).exists()
            subprocess.run(["nft", "delete", "table", "inet", confine.TABLE], check=True)
            try:
                run.popen(["true"], {"PATH": "/usr/bin:/bin"})
                gone = None
            except confine.Unconfined as e:
                gone = str(e)
        check(planted and not (spool / first.pw_name).exists(), "a job a run planted is removed when its lease ends")
        check(gone is not None and "chain" in gone, "a lease whose network chain was flushed starts nothing")
    finally:
        os.environ["KK_RUN_AS"] = pool_was
        confine.SPOOLS = spools

    # A process already running as a run user (another program sharing its uid) is refused, never killed.
    first = confine.pool()[0]
    other = subprocess.Popen(["sleep", "60"], user=first.pw_uid, group=first.pw_gid, extra_groups=[])
    try:
        os.environ["KK_RUN_AS"], pool_was = first.pw_name, os.environ["KK_RUN_AS"]
        try:
            with confine.lease():
                refused = None
        except confine.Unconfined as e:
            refused = str(e)
        finally:
            os.environ["KK_RUN_AS"] = pool_was
        check(refused is not None and "already has processes" in refused and other.poll() is None,
              "a run user that already has processes is refused, and they are left running")
    finally:
        other.kill()
        other.wait()

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
    who, creds, sees, os_user, parent_env, superuser, record = probe.read_text().split()
    check(who.startswith("kk_sbx_") and set(creds.split(",")) <= {"-", "PGHOST", "PGPORT"} and sees == "False",
          f"the candidate runs as a login made for its run ({who}), with no other credentials ({creds}), "
          "and cannot see the run files")
    check(record == "closed", "that login has no way into the record's cluster")
    check(os_user in os.environ["KK_RUN_AS"].split(",") and parent_env == "closed" and superuser == "closed",
          f"the candidate runs as the OS user {os_user}: it cannot read the sandbox's environment ({parent_env}) "
          f"or connect as postgres without a password ({superuser})")
    count = lambda q: subprocess.run(["psql", "-d", "postgres", "-qAtc", q], capture_output=True, text=True).stdout.strip()
    with sandbox_cluster():
        roles = count("select count(*) from pg_roles where rolname like 'kk_sbx_%'")
        left = count("select count(*) from pg_database where datname like 'kk_sbx_%'")
    check(roles == "0" and count("select count(*) from pg_roles where rolname like 'kk_sbx_%'") == "0",
          "the logins made for the runs are dropped (and none was ever made on the record's cluster)")
    check(left == "0" and count("select count(*) from pg_database where datname like 'kk_sbx_%'") == "0",
          "the sandbox databases are dropped (and none was made on the record's cluster)")
    shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
