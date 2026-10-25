"""G3: Morphogen maps a small real system it did not build and completes one governed change on it (R5-25).

  system     podinfo 6.9.2 (frontend -> backend -> Redis), an operator's compose file imported into
             intent/systems/podinfo by a person; deploy/compose.py runs it from the commit
  map        encoder-compose records its services, images, settings and connections, citing each line
  monitor    observer-prometheus scrapes the frontend's and backend's own metrics: mean request time
  analyse    a person documents a limit on the frontend's request time; anomaly finds it over the limit
  plan       the planner follows the map from the frontend to the backend, whose delay setting answers
             it, and proposes lowering it, predicting the frontend's request time within the limit
  approve    a person approves it in the review lane
  execute    the intent actuator commits the new value to the compose file; compose.py applies it
  verify     the prediction verifier compares the frontend's windows after the change with the prediction

Then every step is checked to cite the one before it, the plan citing the map. Needs Docker (images
pulled once) and takes about three minutes.

  PGHOST=... PGUSER=<superuser> python3 morphogen/tests/test_g3.py   (KK_LOOP_LOGS=1 keeps the logs)
"""
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "morphogen" / "modules"
sys.path[:0] = [str(ROOT / "kernel" / "src"), str(MODULES)]
from kk.lib import connect, run, submit  # noqa: E402
import install  # noqa: E402  (morphogen/modules/install.py)

DB = "kk_g3_test"
SOSA = "http://www.w3.org/ns/sosa/"
OA = "http://www.w3.org/ns/oa#"
KKT = "https://w3id.org/knowledge-kernel/tosca#"
MAX = "https://www.irit.fr/recherches/MELODI/ontologies/BBO#maxValue"
LAT = "urn:kk:property:latency-seconds-mean"
FRONT, BACK = "urn:kk:node:podinfo:frontend", "urn:kk:node:podinfo:backend"
PERSON = "urn:kk:agent:g3-person"
WINDOW = int(os.environ.get("KK_LOOP_WINDOW", "4"))
LIMIT = 0.15


def check(cond, msg):
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def wait(what, f, timeout=180.0, every=0.5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        got = f()
        if got:
            return got
        time.sleep(every)
    raise SystemExit(f"CHECK FAILED: timed out waiting for {what}")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=operator", "-c", "user.email=op@example.org", *args],
                          check=True, capture_output=True, text=True).stdout


def main() -> None:
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        raise SystemExit("CHECK FAILED: G3 needs a Docker daemon")
    subprocess.run(["dropdb", "--if-exists", DB], check=True)
    os.environ.setdefault("KK_LOGIN_PASSWORD", secrets.token_hex(16))
    install.install(DB, install.modules())
    url = f"dbname={DB}"
    with connect(url=url) as su:
        su.execute("do $$ begin if not exists (select 1 from pg_roles where rolname = 't_g3_person') then "
                   "create role t_g3_person nologin; end if; end $$")
        su.execute("grant kk_reviewer to t_g3_person")
        su.execute("set role kk_owner")
        su.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, 't_g3_person', 'person', 'G3 person') "
                   "on conflict do nothing", (PERSON,))

    # Morphogen's intent with the operator's compose file, imported by a person (one commit).
    tmp = Path(tempfile.mkdtemp())
    intent = tmp / "intent"
    shutil.copytree(ROOT / "morphogen" / "intent", intent)
    compose_file = intent / "systems" / "podinfo" / "compose.yaml"
    git(intent, "init", "-q")
    git(intent, "add", "-A")
    git(intent, "commit", "-qm", "intent, and podinfo as its operator runs it")

    project = f"kk-g3-{os.getpid()}"
    base_env = {**os.environ, "DATABASE_URL": url, "KK_SWEEP_SECONDS": "30", "KK_POLL_SECONDS": "0.5",
                "KK_INTENT_DIR": str(intent), "KK_INTENT_ENV": "sandbox"}
    path = lambda *dirs: os.pathsep.join([*map(str, dirs), str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "src")])
    procs = []

    def start(name, cmd, cwd, env=None):
        p = subprocess.Popen(cmd, cwd=cwd, env={**base_env, **(env or {})}, stdout=open(tmp / f"{name}.log", "w"),
                             stderr=subprocess.STDOUT)
        procs.append((name, p))
        return p

    def service(name, module, cwd, env=None):
        return start(name, [sys.executable, "-m", module], cwd, {**(env or {}), "PYTHONPATH": path(cwd)})

    stop = threading.Event()
    try:
        start("compose", [sys.executable, str(ROOT / "morphogen" / "deploy" / "compose.py"), "--intent", str(intent),
                          "--system", "podinfo", "--project", project], ROOT, {"KK_RECONCILE_SECONDS": "1"})
        wait("podinfo to start", lambda: '"started"' in (tmp / "compose.log").read_text(), timeout=600, every=1)
        port = lambda s: subprocess.run(["docker", "compose", "-p", project, "port", s, "9898"], capture_output=True,
                                        text=True, check=True).stdout.strip().rsplit(":", 1)[-1]
        front, back = f"http://127.0.0.1:{port('frontend')}", f"http://127.0.0.1:{port('backend')}"
        check(json.loads(urllib.request.urlopen(front + "/version", timeout=10).read())["version"] == "6.9.2",
              "the system runs from the operator's committed compose file (podinfo 6.9.2)")

        # Map it.
        enc = MODULES / "encoder-compose"
        out = subprocess.run([sys.executable, "-m", "encoder_compose", "scan", "--system", "podinfo", "--file", str(compose_file),
                              "--repo", str(intent)], cwd=enc, env={**base_env, "PYTHONPATH": path(enc)},
                             capture_output=True, text=True)
        check(out.returncode == 0, "encoder-compose maps the system: " + (out.stdout + out.stderr).strip()[-300:])

        # The kernel providers (validator, belief model, anomaly) from intent, and the loop's services.
        start("reconcile", [sys.executable, str(ROOT / "morphogen" / "deploy" / "reconcile.py"), "--intent", str(intent),
                            "--env", "sandbox", "--repo", str(ROOT)], ROOT)
        service("observer", "observer_prometheus", MODULES / "observer-prometheus",
                {"KK_WINDOW_SECONDS": str(WINDOW), "KK_PROM_TARGETS": f"{FRONT}={front}/metrics,{BACK}={back}/metrics"})
        service("planner", "planner", MODULES / "planner")
        service("actuator", "intent_actuator", MODULES / "intent-actuator")
        service("verifier", "prediction_verifier", MODULES / "prediction-verifier",
                {"KK_OBSERVER_AGENTS": "urn:kk:agent:observer-prometheus"})

        def traffic():                          # two clients calling the frontend, which calls the backend
            while not stop.is_set():
                try:
                    urllib.request.urlopen(urllib.request.Request(front + "/api/echo", data=b"g3", method="POST"), timeout=10).read()
                except Exception:
                    time.sleep(0.2)
        for _ in range(2):
            threading.Thread(target=traffic, daemon=True).start()

        with connect("t_g3_person", url) as person:
            q = lambda sql, *a: person.execute(sql, a).fetchall()
            links = wait("the map in the record", lambda: q(
                "select c.id, r.references from api.claims c cross join lateral (select api.explain(c.id)->'references' as references) r "
                "where c.subject = %s and c.predicate = %s and c.object_entity = %s and c.attributed_to = 'urn:kk:agent:encoder-compose'",
                FRONT, KKT + "connectsTo", BACK))
            check(links[0][1][0]["source_uri"] == "file:systems/podinfo/compose.yaml"
                  and links[0][1][0]["span"]["value"].startswith("line="),
                  "map: the frontend connects to the backend, citing the compose file's line")
            check(q("select object_value->>'@value' from api.claims where subject = %s and predicate = %s and qualifiers->>%s = %s",
                    BACK, KKT + "propertyValue", KKT + "propertyName", "PODINFO_RANDOM_DELAY_MAX")[0][0] == "600",
                  "map: the backend's delay setting as the operator wrote it (600)")

            with person.cursor() as cur, run(cur, "urn:kk:module:g3-person") as (run_id, _):
                submit(cur, {"idempotency_key": "g3:limit", "attributed_to": PERSON, "target_scope": "urn:kk:scope:default",
                             "ops": [{"op": "add_claim", "subject": FRONT, "predicate": MAX,
                                      "object": {"value": {"@value": LIMIT}}, "qualifiers": {SOSA + "observedProperty": LAT},
                                      "evidence_type": "testimony", "references": [{"source_uri": "urn:kk:test:g3#limit"}]}]}, run_id)
            check(wait("the limit to apply", lambda: q("select 1 from api.claims where predicate = %s and subject = %s", MAX, FRONT)),
                  f"a person's documented limit: the frontend answers within {LIMIT} s on average")
            obs = wait("an observation of the frontend", lambda: q(
                "select (object_value->>'@value')::float from api.claims where subject = %s and predicate = %s "
                "and attributed_to = 'urn:kk:agent:observer-prometheus' order by valid_from", FRONT, SOSA + "hasSimpleResult"))
            check(obs[0][0] > LIMIT, f"monitor: the observer records the frontend's request time from its metrics ({obs[0][0]:g} s)")
            anomaly = wait("an anomaly", lambda: q("select subject from api.claims where predicate = %s and object_entity = %s "
                                                   "and attributed_to = 'urn:kk:agent:anomaly' and subject in (select subject from "
                                                   "api.claims where object_entity = 'urn:kk:anomaly-kind:limit')", OA + "hasTarget", FRONT))[0][0]
            check(anomaly.startswith("urn:kk:anomaly:"), "analyse: the frontend over its limit is an anomaly")
            queue = wait("a plan in the review queue", lambda: q("select id, ops from api.review_queue where attributed_to = 'urn:kk:agent:planner'"))
            check(len(queue) == 1, "plan: one plan, waiting for a person")
            cs_id, ops = queue[0]
            step = next(o["subject"] for o in ops if o["predicate"].endswith("hasFeatureOfInterest"))
            target = next(o["object"]["entity"] for o in ops if o["predicate"].endswith("hasFeatureOfInterest"))
            new = next(o["object"]["value"]["@value"] for o in ops if o["predicate"].endswith("hasSimpleResult"))
            pred = next(o for o in ops if o["predicate"] == MAX)
            check(target == BACK and 0 < float(new) < 600 and pred["subject"] == FRONT and pred["object"]["value"]["@value"] == LIMIT,
                  f"the plan changes the backend's delay (600 -> {new}) and predicts the frontend within {LIMIT} s")
            check(str(links[0][0]) in next(o["derived_from"] for o in ops if o["predicate"] == MAX),
                  "the plan cites the map: the connection from the frontend to the backend")

            person.execute("select api.review(%s, true, 'go ahead')", (cs_id,))
            check(q("select status from api.change_sets where id = %s", cs_id)[0][0] == "applied", "approve: a person approves the plan")
            run_row = wait("the actuator to carry out the step", lambda: q(
                "select status, outputs from kernel.run where agent = 'urn:kk:agent:intent-actuator' and plan_step = %s and ended_at is not null", step))
            check(run_row[0][0] == "succeeded" and run_row[0][1]["before"] == "600", "execute: the intent actuator carried out the step")
            msg = git(intent, "log", "-1", "--format=%B")
            check(msg.startswith(f"change-set:{cs_id} plan-step:{step}")
                  and f'PODINFO_RANDOM_DELAY_MAX: "{run_row[0][1]["after"]}"' in compose_file.read_text(),
                  "the change is one commit to the compose file, naming the change set and the step")
            check(not q("select 1 from api.claims where attributed_to = 'urn:kk:agent:intent-actuator'"), "the actuator wrote no claims")
            wait("compose.py to apply it", lambda: '"updated"' in (tmp / "compose.log").read_text(), timeout=120)

            verdict = wait("a verdict", lambda: q("select v.subject, t.object_entity from api.claims v join api.claims t on t.subject = v.subject "
                                                 "where v.subject like 'urn:kk:verdict:%%' and v.predicate = %s and t.predicate = %s",
                                                 OA + "hasTarget", "http://purl.org/dc/terms/type"), timeout=180)
            check(verdict[0][1] == "urn:kk:verdict:holds", f"verify: the prediction holds ({verdict[0][1]})")

            prem = lambda subject: {r[0] for r in q("select d.derived_from::text from kernel.claim_derivation d join api.claims c on c.id = d.claim_id "
                                                    "where c.subject = %s", subject)}
            attributed = lambda ids: {r[0] for r in q("select attributed_to from api.claims where id = any(%s::uuid[])", list(ids))}
            plan = next(o["subject"] for o in ops if o["predicate"].endswith("isStepOfPlan"))
            check(attributed(prem(verdict[0][0])) == {"urn:kk:agent:planner", "urn:kk:agent:observer-prometheus"},
                  "the verdict cites the planner's prediction and the observer's windows")
            check({"urn:kk:agent:anomaly", "urn:kk:agent:observer-prometheus", "urn:kk:agent:encoder-compose", PERSON} <= attributed(prem(plan)),
                  "the plan cites the anomaly, the observation, the person's limit and the map")
            check({"urn:kk:agent:observer-prometheus", PERSON} == attributed(prem(anomaly)), "the anomaly cites the observation and the limit")
            check(q("select lane from api.change_sets where id = %s", cs_id)[0][0] == "review", "the plan went through the review lane")
    finally:
        stop.set()
        for name, p in reversed(procs):
            p.terminate()
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()
        subprocess.run(["docker", "compose", "-p", project, "down", "-v", "-t", "1"], capture_output=True)
        if os.environ.get("KK_LOOP_LOGS"):
            print(f"logs: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    subprocess.run(["dropdb", "--force", DB], check=True)
    print("G3 passed")


if __name__ == "__main__":
    main()
