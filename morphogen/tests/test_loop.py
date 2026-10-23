"""T5: one full loop on Morphogen's own stack, every step a separate service on one record.

  monitor    the belief model (a kernel provider, run by the reconciler from intent) reports its feed lag
             over OpenTelemetry; observer-otel records each window's mean as an observation
  analyse    anomaly finds the lag over the limit a person documented
  plan       the planner proposes halving the belief model's poll interval, predicting the lag will
             stay within the limit, in the lane the autonomy policy gives it; the store sends it to review
  approve    a person approves it in the review lane
  execute    the intent actuator commits the new setting to intent/ (it writes no claims); the reconciler
             restarts the belief model with it
  verify     the prediction verifier, not the planner, compares the windows after the change with the
             prediction and records the verdict

Then every step is checked to cite the one before it. Takes about a minute.

  PGHOST=... PGUSER=<superuser> python3 morphogen/tests/test_loop.py   (needs psycopg, PyYAML, pyshacl, git)
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "morphogen" / "modules"
sys.path[:0] = [str(ROOT / "kernel" / "src"), str(MODULES)]
from kk.lib import connect, run, submit  # noqa: E402
import install  # noqa: E402  (morphogen/modules/install.py)

DB = "kk_loop_test"
SOSA = "http://www.w3.org/ns/sosa/"
OA = "http://www.w3.org/ns/oa#"
MAX = "https://www.irit.fr/recherches/MELODI/ontologies/BBO#maxValue"
LAG = "urn:kk:property:feed-lag-seconds-mean"
BELIEF = "urn:kk:provider:belief-corroboration"
PERSON = "urn:kk:agent:loop-person"
LOAD = "urn:kk:agent:loop-load"
WINDOW = int(os.environ.get("KK_LOOP_WINDOW", "4"))   # seconds per observation window


def check(cond, msg):
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def wait(what, f, timeout=120.0, every=0.5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        got = f()
        if got:
            return got
        time.sleep(every)
    raise SystemExit(f"CHECK FAILED: timed out waiting for {what}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=loop-test", "-c", "user.email=t@t", *args],
                          check=True, capture_output=True, text=True).stdout


def main() -> None:
    subprocess.run(["dropdb", "--if-exists", DB], check=True)
    install.install(DB, install.modules())
    url = f"dbname={DB}"
    with connect(url=url) as su:
        for role, base, iri, kind in (("t_loop_person", "kk_reviewer", PERSON, "person"),
                                      ("t_loop_load", "kk_agent", LOAD, "software")):
            su.execute(f"do $$ begin if not exists (select 1 from pg_roles where rolname = '{role}') then "
                       f"create role {role} nologin; end if; end $$")
            su.execute(f"grant {base} to {role}")
            su.execute("set role kk_owner")
            su.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, %s, %s, %s) on conflict do nothing",
                       (iri, role, kind, role))
            su.execute("reset role")

    # Morphogen's intent, in its own git work tree; the belief model starts slow (polls every 4 s).
    tmp = Path(tempfile.mkdtemp())
    intent = tmp / "intent"
    shutil.copytree(ROOT / "morphogen" / "intent", intent)
    f = intent / "environments" / "sandbox" / "belief-corroboration.yaml"
    f.write_text(f.read_text().replace('KK_POLL_SECONDS: "1"', 'KK_POLL_SECONDS: "4"'))
    git(intent, "init", "-q")
    git(intent, "add", "-A")
    git(intent, "commit", "-qm", "intent")

    port = free_port()
    base_env = {**os.environ, "DATABASE_URL": url, "KK_SWEEP_SECONDS": "30", "KK_POLL_SECONDS": "0.5",
                "KK_INTENT_DIR": str(intent), "KK_INTENT_ENV": "sandbox"}
    path = lambda *dirs: os.pathsep.join([*map(str, dirs), str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "src")])
    procs = []

    def service(name, module, cwd, env):
        log = open(tmp / f"{name}.log", "w")
        p = subprocess.Popen([sys.executable, "-m", module], cwd=cwd, env={**base_env, **env, "PYTHONPATH": path(cwd)},
                             stdout=log, stderr=subprocess.STDOUT)
        procs.append((name, p))
        return p

    stop = threading.Event()
    try:
        token = os.urandom(16).hex()
        service("observer", "observer_otel", MODULES / "observer-otel",
                {"KK_WINDOW_SECONDS": str(WINDOW), "KK_OTLP_PORT": str(port), "KK_OTLP_SOURCE": f"http://observer:{port}/v1/metrics",
                 "KK_OTLP_TOKEN": token, "KK_OTLP_SERVICES": "belief-corroboration,validator-shacl"})
        for name, module in (("anomaly", "anomaly"), ("planner", "planner"), ("actuator", "intent_actuator"),
                             ("verifier", "prediction_verifier")):
            service(name, module, MODULES / {"actuator": "intent-actuator", "verifier": "prediction-verifier"}.get(name, name), {})
        log = open(tmp / "reconcile.log", "w")
        rec = subprocess.Popen([sys.executable, str(ROOT / "morphogen" / "deploy" / "reconcile.py"), "--intent", str(intent),
                                "--env", "sandbox", "--repo", str(ROOT)],
                               env={**base_env, "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{port}",
                                    "OTEL_EXPORTER_OTLP_HEADERS": f"Authorization=Bearer%20{token}",
                                    "OTEL_METRIC_EXPORT_INTERVAL": "1000"}, stdout=log, stderr=subprocess.STDOUT)
        procs.append(("reconcile", rec))

        with connect("t_loop_person", url) as person, connect("t_loop_load", url) as load:
            with person.cursor() as cur, run(cur, "urn:kk:module:loop-person") as (run_id, _):
                submit(cur, {"idempotency_key": "loop:limit", "attributed_to": PERSON, "target_scope": "urn:kk:scope:default",
                             "ops": [{"op": "add_claim", "subject": BELIEF, "predicate": MAX,
                                      "object": {"value": {"@value": 1.0}}, "qualifiers": {SOSA + "observedProperty": LAG},
                                      "evidence_type": "testimony",
                                      "references": [{"source_uri": "urn:kk:test:loop#limit"}]}]}, run_id)

            def generate():                       # work for the belief model: a small change set every 0.3 s
                n = 0
                while not stop.is_set():
                    try:
                        with load.cursor() as cur, run(cur, "urn:kk:module:loop-load") as (rid, _):
                            submit(cur, {"idempotency_key": f"loop:load:{n}", "attributed_to": LOAD,
                                         "target_scope": "urn:kk:scope:default",
                                         "ops": [{"op": "add_claim", "subject": f"urn:x:load:{n}", "predicate": "rdfs:label",
                                                  "object": {"value": {"@value": f"item {n}"}}, "evidence_type": "deterministic",
                                                  "references": [{"source_uri": f"urn:kk:test:loop#{n}"}]}]}, rid)
                    except Exception as e:
                        print("load:", e, flush=True)
                    n += 1
                    stop.wait(0.3)
            threading.Thread(target=generate, daemon=True).start()

            q = lambda sql, *a: person.execute(sql, a).fetchall()
            check(wait("the limit to apply", lambda: q("select 1 from api.claims where predicate = %s and subject = %s", MAX, BELIEF)),
                  "a person's documented limit: the belief model's feed lag stays within 1 s")
            obs = wait("an observation of the belief model's lag", lambda: q(
                "select id, (object_value->>'@value')::float from api.claims where subject = %s and predicate = %s "
                "and attributed_to = 'urn:kk:agent:observer-otel' and qualifiers->>%s = %s order by valid_from", BELIEF, SOSA + "hasSimpleResult",
                SOSA + "observedProperty", LAG))
            check(obs[0][1] > 1.0, f"monitor: the observer records the lag from OpenTelemetry ({obs[0][1]:g} s)")
            anomaly = wait("an anomaly", lambda: q("select subject from api.claims where predicate = %s and object_entity = %s "
                                                   "and attributed_to = 'urn:kk:agent:anomaly'", OA + "hasTarget", BELIEF))[0][0]
            check(anomaly.startswith("urn:kk:anomaly:"), "analyse: the lag over the limit is an anomaly on the belief model")
            queue = wait("a plan in the review queue", lambda: q("select id, ops from api.review_queue where attributed_to = 'urn:kk:agent:planner'"))
            check(len(queue) == 1, "plan: one plan, waiting for a person (the store forces review for plan steps)")
            cs_id, ops = queue[0]
            step = next(o["subject"] for o in ops if o["predicate"].endswith("hasFeatureOfInterest"))
            check(any(o["predicate"] == MAX and o["qualifiers"].get("http://purl.org/dc/terms/isPartOf") for o in ops)
                  and any(o["predicate"].endswith("hasSimpleResult") and o["object"]["value"]["@value"] == 1.0 for o in ops),
                  "the plan sets the poll interval to 1 s and predicts the lag within its limit")
            check(not q("select 1 from api.claims where subject = %s", step), "nothing of the plan is in the record before approval")

            person.execute("select api.review(%s, true, 'go ahead')", (cs_id,))
            check(q("select status from api.change_sets where id = %s", cs_id)[0][0] == "applied", "approve: a person approves the plan")

            run_row = wait("the actuator to carry out the step", lambda: q(
                "select status, cost from kernel.run where agent = 'urn:kk:agent:intent-actuator' and plan_step = %s and ended_at is not null", step))
            check(run_row[0][0] == "succeeded" and run_row[0][1]["after"] == "1", "execute: the intent actuator carried out the step")
            msg = git(intent, "log", "-1", "--format=%B")
            check(msg.startswith(f"change-set:{cs_id} plan-step:{step}") and 'KK_POLL_SECONDS: "1"' in f.read_text(),
                  "the change is one commit to intent, naming the change set and the step")
            check(not q("select 1 from api.claims where attributed_to = 'urn:kk:agent:intent-actuator'"), "the actuator wrote no claims")
            wait("the reconciler to restart the belief model", lambda: "restarting" in (tmp / "reconcile.log").read_text(), timeout=30)

            verdict = wait("a verdict", lambda: q("select v.subject, t.object_entity from api.claims v join api.claims t on t.subject = v.subject "
                                                 "where v.subject like 'urn:kk:verdict:%%' and v.predicate = %s and t.predicate = %s",
                                                 OA + "hasTarget", "http://purl.org/dc/terms/type"), timeout=120)
            plan = next(o["subject"] for o in ops if o["predicate"].endswith("isStepOfPlan"))
            check(verdict[0][1] == "urn:kk:verdict:holds", f"verify: the prediction holds ({verdict[0][1]})")

            # Every step cites the one before it.
            prem = lambda subject: {r[0] for r in q("select d.derived_from::text from kernel.claim_derivation d join api.claims c on c.id = d.claim_id "
                                                    "where c.subject = %s", subject)}
            attributed = lambda ids: {r[0] for r in q("select attributed_to from api.claims where id = any(%s::uuid[])", list(ids))}
            check(attributed(prem(verdict[0][0])) == {"urn:kk:agent:planner", "urn:kk:agent:observer-otel"},
                  "the verdict cites the planner's prediction and the observer's windows")
            check(q("select attributed_to from api.claims where subject = %s limit 1", verdict[0][0])[0][0] == "urn:kk:agent:prediction-verifier",
                  "the verdict is not the planner's (invariant 5)")
            check({"urn:kk:agent:anomaly", "urn:kk:agent:observer-otel", PERSON} <= attributed(prem(plan)),
                  "the plan cites the anomaly, the observation and the person's limit")
            check({"urn:kk:agent:observer-otel", PERSON} == attributed(prem(anomaly)), "the anomaly cites the observation and the limit")
            lane = q("select lane from api.change_sets where id = %s", cs_id)
            check(lane and lane[0][0] == "review", "the plan went through the review lane")
    finally:
        stop.set()
        for name, p in reversed(procs):
            p.terminate()
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()
        if os.environ.get("KK_LOOP_LOGS"):           # keep the logs and the intent repository to look at
            print(f"logs: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    print("T5 loop passed")


if __name__ == "__main__":
    main()
