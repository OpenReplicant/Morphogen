"""The anomaly service keeps a durable cursor (R5-18, T15): down while an observer records a spike and four
windows after it, it finds the spike on start (the latest 3 windows of all would miss it); the run records the
feed seq it reached; a restart with nothing new starts no run; a crash between submit and finish leaves the
cursor where it was and the next pass submits nothing twice; a new limit re-judges its series' latest 3 windows
only, and so does a withdrawn window; one change set's spike before its latest 3 windows is not judged;
beliefs on older windows and entries it does not watch start no run.

  PGHOST=... PGUSER=<superuser> python3 tests/test_service.py
"""
import importlib
import os
import secrets
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "modules"),
                str(ROOT / "kernel" / "providers" / "validator-shacl")]
import install  # noqa: E402  (morphogen/modules/install.py)
import anomaly.__main__ as svc  # noqa: E402
from anomaly.detect import MAX, PROP, RESULT  # noqa: E402
from kk.lib import connect, feed_head, resume, run, submit  # noqa: E402

validator = importlib.import_module("validator.__main__")

DB = "kk_anomaly_test"
URL = f"dbname={DB}"
OBSERVER = "urn:kk:agent:anomaly-test-observer"
NODE = "urn:kk:node:shop"
LATENCY = "urn:kk:property:latency-seconds-mean"
XSD = "http://www.w3.org/2001/XMLSchema#decimal"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
STEADY = [0.010, 0.012, 0.011]


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg)


def settle():
    with connect("kkm_validator", URL) as val:
        validator.drain(val)


def record(key: str, ops: list[dict]) -> None:
    with connect("t_anomaly_observer", URL) as conn, conn.cursor() as cur, \
            run(cur, "urn:kk:module:anomaly-test-observer") as (rid, _):
        submit(cur, {"idempotency_key": key, "attributed_to": OBSERVER, "target_scope": "urn:kk:scope:default",
                     "ops": ops}, rid)
    settle()


def obs(w: int, value: float, node: str = NODE) -> dict:
    t = T0 + timedelta(minutes=w)
    return {"op": "add_claim", "subject": node, "predicate": RESULT,
            "object": {"value": {"@value": value, "@type": XSD}}, "qualifiers": {PROP: LATENCY},
            "valid_from": t.isoformat(), "valid_to": (t + timedelta(minutes=1)).isoformat(),
            "evidence_type": "observed", "references": [{"source_uri": f"urn:test:anomaly/{node}/obs/{w}"}]}


def window(w: int, value: float) -> None:
    record(f"obs:{w}", [obs(w, value)])


def start() -> dict:
    """A pass of a freshly started service: nothing kept in memory, only what its runs recorded."""
    svc._cursor.clear()
    with connect("kkm_anomaly", URL) as conn:
        res = svc.one_pass(conn)
    settle()
    return res


def anomalies(conn, node: str = NODE) -> dict:
    """{(kind, window): count} of the anomalies on `node`, by the window they are valid for (their observation's)."""
    rows = conn.execute("select k.object_entity, k.valid_from from api.claims k join api.claims t on t.subject = k.subject "
                        "and t.predicate = 'http://www.w3.org/ns/oa#hasTarget' and t.object_entity = %s "
                        "where k.predicate = 'http://purl.org/dc/terms/type' and k.attributed_to = %s", (node, svc.AGENT)).fetchall()
    out: dict = {}
    for kind, at in rows:
        k = (kind.rsplit(":", 1)[-1], int((at - T0).total_seconds() // 60))
        out[k] = out.get(k, 0) + 1
    return out


def runs(conn) -> int:
    return conn.execute("select count(*) from kernel.run where module = %s", (svc.MODULE,)).fetchone()[0]


subprocess.run(["dropdb", "--if-exists", DB], check=True)
os.environ.setdefault("KK_LOGIN_PASSWORD", secrets.token_hex(16))
install.install(DB, ["anomaly"])
os.environ["DATABASE_URL"] = URL
with connect(url=URL) as su:
    su.execute("do $$ begin if not exists (select 1 from pg_roles where rolname = 't_anomaly_observer') then "
               "create role t_anomaly_observer nologin; end if; end $$")
    su.execute("grant kk_agent to t_anomaly_observer")
    su.execute("set role kk_owner")
    su.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, 't_anomaly_observer', 'software', "
               "'anomaly test observer') on conflict do nothing", (OBSERVER,))

# Ten steady windows, a spike, four steady windows: one change set each, the service down throughout.
for w in range(10):
    window(w, STEADY[w % 3])
window(10, 1.0)
for w in range(11, 15):
    window(w, STEADY[w % 3])
with connect("kkm_anomaly", URL) as conn:
    head = feed_head(conn)
first = start()
with connect("kkm_anomaly", URL) as conn:
    got = anomalies(conn)
    check(got == {("zscore", 10): 1}, f"down while 5 windows arrived, it finds the spike 5 windows back on start ({got})")
    check(resume(conn, svc.MODULE) == head, "its run records the feed seq it reached; resume reads it back")
    n = runs(conn)

# Restarted with nothing new: no run, nothing submitted.
again = start()
with connect("kkm_anomaly", URL) as conn:
    check(again == {"anomalies": {}} and runs(conn) == n, "a restart with nothing new starts no run and submits nothing")

# A crash between submit and finish: the run fails, the cursor stays; the next pass submits nothing twice.
window(15, 2.5)
real = svc.submit


def crash(cur, cs, run_id):
    res = real(cur, cs, run_id)
    raise RuntimeError("killed between submit and finish")


svc.submit = crash
try:
    start()
    check(False, "the crashing pass raises")
except RuntimeError:
    pass
finally:
    svc.submit = real
settle()
with connect("kkm_anomaly", URL) as conn:
    check(resume(conn, svc.MODULE) == head, "a failed run does not move the cursor")
    check(anomalies(conn).get(("zscore", 15)) == 1, "what the crashed run submitted was applied")
redo = start()
with connect("kkm_anomaly", URL) as conn:
    got = anomalies(conn)
    check(redo == {"anomalies": {}} and got.get(("zscore", 15)) == 1,
          "the next pass reads the same entries again and submits nothing twice (the idempotency key)")
    check(resume(conn, svc.MODULE) == feed_head(conn) > head, "and its run moves the cursor past them")

# A documented limit re-judges its series' latest 3 windows, not the history.
record("limit", [{"op": "add_claim", "subject": NODE, "predicate": MAX, "object": {"value": {"@value": 0.005, "@type": XSD}},
                  "qualifiers": {PROP: LATENCY}, "evidence_type": "testimony", "references": [{"source_uri": "urn:test:anomaly/limit"}]}])
start()
with connect("kkm_anomaly", URL) as conn:
    limits = sorted(w for (k, w) in anomalies(conn) if k == "limit")
    check(limits == [13, 14, 15], f"a new limit judges the latest 3 windows only ({limits})")
    newest = conn.execute("select id from api.claims where predicate = %s and valid_from = %s",
                          (RESULT, T0 + timedelta(minutes=15))).fetchone()[0]

# The newest window withdrawn: the one before the latest 3 is among them again and judged.
record("retract", [{"op": "set_status", "claim": str(newest), "status": "deprecated", "reason": "retracted"}])
start()
with connect("kkm_anomaly", URL) as conn:
    limits = sorted(w for (k, w) in anomalies(conn) if k == "limit")
    check(limits == [12, 13, 14, 15], f"a withdrawn window re-judges its series' latest 3 ({limits})")
    n = runs(conn)

# One change set of eleven windows of another series, its spike 5 windows back: only its latest 3 are judged.
BATCH = "urn:kk:node:batch"
record("batch", [obs(w, 1.0 if w == 6 else STEADY[w % 3], BATCH) for w in range(11)])
start()
with connect("kkm_anomaly", URL) as conn:
    got = anomalies(conn, BATCH)
    check(got == {}, f"one change set of 11 windows: its latest 3 are judged, not the spike before them ({got})")
    n = runs(conn)
    old = [str(r[0]) for r in conn.execute("select id from api.claims where predicate = %s and subject = %s "
                                           "and status <> 'deprecated'", (RESULT, NODE)).fetchall()]

# Beliefs on older windows (as belief-corroboration rescores a subject) record no window: no run.
record("beliefs", [{"op": "add_belief", "claim": i, "model": "urn:kk:model:anomaly-test", "value": 0.9} for i in old])
start()
with connect("kkm_anomaly", URL) as conn:
    scored = conn.execute("select count(*) from kernel.belief where model = 'urn:kk:model:anomaly-test'").fetchone()[0]
    check(scored == len(old) > 0 and runs(conn) == n, f"an entry that only scores older windows ({scored}) starts no run and judges nothing")

# An entry it does not watch starts no run.
record("other", [{"op": "add_claim", "subject": NODE, "predicate": "http://www.w3.org/2000/01/rdf-schema#label",
                  "object": {"value": {"@value": "shop"}}, "evidence_type": "testimony",
                  "references": [{"source_uri": "urn:test:anomaly/label"}]}])
with connect("kkm_anomaly", URL) as conn:
    res = svc.one_pass(conn)
    check(res == {"anomalies": {}} and runs(conn) == n, "an entry carrying nothing it watches starts no run")
print("anomaly service checks passed")
