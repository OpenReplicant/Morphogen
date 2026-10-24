"""G2: Morphogen changes one of its own providers through the loop, and the observed result matches the
prediction. Every step is a separate service on one record; every step cites the one before it.

  monitor    the analyser (anomaly, run by the reconciler from intent) reports its own step time over
             OpenTelemetry; the record holds 4,500 earlier observations, so its pass is slow
  analyse    the analyser finds its own step time over the limit a person documented: KK_G2_LIMIT_RATIO
             (0.7) of the incumbent's second observed window, so the gate does not depend on the machine's
             speed (the candidates measured so far run at 0.4-0.55 of the incumbent); KK_G2_LIMIT fixes it
  request    the planner asks for a better provider of the analyser slot (a build request, auto lane)
  build      the builder writes a candidate into intent/experiments/ and commits it (CI: a fixture)
  measure    the sandbox runs the analyser contract on candidate and incumbent and measures both on a copy
             of the record; the evaluator records the scores
  plan       the planner proposes the replacement, predicting the candidate's step time within the limit
  approve    a person approves it in the review lane
  execute    the intent actuator commits the switch; the reconciler runs the candidate
  verify     the prediction verifier compares the candidate's observed step time with the prediction

  PGHOST=... PGUSER=<superuser> python3 morphogen/tests/test_g2.py   (about two minutes; KK_LOOP_LOGS=1 keeps the logs)
"""
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "morphogen" / "modules"
sys.path[:0] = [str(ROOT / "kernel" / "src"), str(MODULES)]
from psycopg.types.json import Jsonb  # noqa: E402

from kk.lib import connect, run, submit  # noqa: E402
import install  # noqa: E402  (morphogen/modules/install.py)

DB = "kk_g2_test"
SOSA = "http://www.w3.org/ns/sosa/"
OA = "http://www.w3.org/ns/oa#"
DCT = "http://purl.org/dc/terms/"
MAX = "https://www.irit.fr/recherches/MELODI/ontologies/BBO#maxValue"
STEP = "urn:kk:property:step-seconds-mean"
ANALYSER = "urn:kk:provider:anomaly"
PERSON = "urn:kk:agent:g2-person"
WINDOW = 4
RATIO = float(os.environ.get("KK_G2_LIMIT_RATIO", "0.7"))   # the limit, as a share of the incumbent's step time


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


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=g2-test", "-c", "user.email=t@t", *args],
                          check=True, capture_output=True, text=True).stdout


def history(targets: int, windows: int) -> list[dict]:
    """Earlier observations of other providers: the record the analyser reads on every pass."""
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return [{"op": "add_claim", "subject": f"urn:kk:provider:earlier-{t}", "predicate": SOSA + "hasSimpleResult",
             "object": {"value": {"@value": 0.01 + 0.001 * (w % 3), "@type": "http://www.w3.org/2001/XMLSchema#decimal"}},
             "qualifiers": {SOSA + "observedProperty": STEP},
             "valid_from": (t0 + timedelta(minutes=w)).isoformat(), "valid_to": (t0 + timedelta(minutes=w + 1)).isoformat(),
             "evidence_type": "observed", "references": [{"source_uri": "urn:kk:test:g2-history"}]}
            for t in range(targets) for w in range(windows)]


def main() -> None:
    subprocess.run(["dropdb", "--if-exists", DB], check=True)
    os.environ.setdefault("KK_LOGIN_PASSWORD", secrets.token_hex(16))   # the modules' own logins (R5-22)
    install.install(DB, install.modules())
    url = f"dbname={DB}"
    with connect(url=url) as su:
        su.execute("do $$ begin if not exists (select 1 from pg_roles where rolname = 't_g2_person') then "
                   "create role t_g2_person nologin; end if; end $$")
        su.execute("grant kk_reviewer to t_g2_person")
        su.execute("set role kk_owner")
        su.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, 't_g2_person', 'person', 'G2 person') "
                   "on conflict do nothing", (PERSON,))
        su.execute("select kernel.install_ops('test:g2-history', 'urn:kk:scope:default', %s)", (Jsonb(history(30, 150)),))

    # Morphogen's intent in its own git work tree: the validator and the analyser run from it.
    tmp = Path(tempfile.mkdtemp())
    intent = tmp / "intent"
    shutil.copytree(ROOT / "morphogen" / "intent", intent)
    (intent / "environments" / "sandbox" / "belief-corroboration.yaml").unlink()
    git(intent, "init", "-q")
    git(intent, "add", "-A")
    git(intent, "commit", "-qm", "intent")

    port = free_port()
    token = os.urandom(16).hex()
    base_env = {**os.environ, "DATABASE_URL": url, "KK_SWEEP_SECONDS": "30", "KK_POLL_SECONDS": "0.5",
                "KK_INTENT_DIR": str(intent), "KK_INTENT_ENV": "sandbox", "KK_ARTIFACTS": str(tmp / "artifacts")}
    path = lambda *dirs: os.pathsep.join([*map(str, dirs), str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "src")])
    procs = []

    def service(name, module, cwd, env):
        log = open(tmp / f"{name}.log", "w")
        p = subprocess.Popen([sys.executable, "-m", module], cwd=cwd, env={**base_env, **env, "PYTHONPATH": path(cwd)},
                             stdout=log, stderr=subprocess.STDOUT)
        procs.append((name, p))

    try:
        service("observer", "observer_otel", MODULES / "observer-otel",
                {"KK_WINDOW_SECONDS": str(WINDOW), "KK_OTLP_PORT": str(port), "KK_OTLP_SOURCE": f"http://observer:{port}/v1/metrics",
                 "KK_OTLP_TOKEN": token, "KK_OTLP_SERVICES": "validator-shacl,anomaly*"})
        service("planner", "planner", MODULES / "planner", {})
        builder = os.environ.get("KK_G2_BUILDER", "fixture")    # harness: KK_BUILDER_COMMAND runs an agent harness
        service("builder", "builder", MODULES / "builder",
                {"KK_BUILDER_STRATEGY": builder, "KK_BUILDER_FIXTURES": str(ROOT / "morphogen" / "tests" / "fixtures")})
        service("sandbox", "sandbox", MODULES / "sandbox", {"KK_BENCH_SECONDS": "6"})
        service("actuator", "intent_actuator", MODULES / "intent-actuator", {})
        service("verifier", "prediction_verifier", MODULES / "prediction-verifier", {})
        log = open(tmp / "reconcile.log", "w")
        procs.append(("reconcile", subprocess.Popen(
            [sys.executable, str(ROOT / "morphogen" / "deploy" / "reconcile.py"), "--intent", str(intent), "--env", "sandbox",
             "--repo", str(ROOT)],
            env={**base_env, "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{port}",
                 "OTEL_EXPORTER_OTLP_HEADERS": f"Authorization=Bearer%20{token}", "OTEL_METRIC_EXPORT_INTERVAL": "1000"},
            stdout=log, stderr=subprocess.STDOUT)))

        with connect("t_g2_person", url) as person:
            q = lambda sql, *a: person.execute(sql, a).fetchall()
            observed = lambda subject: [float(v) for (v,) in q(
                "select object_value->>'@value' from api.claims where subject = %s and predicate = %s and qualifiers->>%s = %s "
                "and attributed_to = 'urn:kk:agent:observer-otel' order by valid_from", subject, SOSA + "hasSimpleResult",
                SOSA + "observedProperty", STEP)]
            # The first window is a warm-up; the second is the incumbent's own pace on this machine.
            first = wait("two observations of the analyser's step time", lambda: (lambda o: o if len(o) >= 2 else None)(observed(ANALYSER)))
            LIMIT = float(os.environ["KK_G2_LIMIT"]) if os.environ.get("KK_G2_LIMIT") else round(RATIO * first[1], 4)
            with person.cursor() as cur, run(cur, "urn:kk:module:g2-person") as (run_id, _):
                submit(cur, {"idempotency_key": "g2:limit", "attributed_to": PERSON, "target_scope": "urn:kk:scope:default",
                             "ops": [{"op": "add_claim", "subject": ANALYSER, "predicate": MAX,
                                      "object": {"value": {"@value": LIMIT}}, "qualifiers": {SOSA + "observedProperty": STEP},
                                      "evidence_type": "testimony", "references": [{"source_uri": "urn:kk:test:g2#limit"}]}]}, run_id)
            check(first[1] > LIMIT, f"monitor: the analyser's own step time is observed ({first[1]:.3f} s); a person sets its limit at {LIMIT} s")
            anomaly = wait("an anomaly on the analyser", lambda: q("select subject from api.claims where predicate = %s and object_entity = %s",
                                                                OA + "hasTarget", ANALYSER))[0][0]
            check(anomaly.startswith("urn:kk:anomaly:"), "analyse: the analyser finds its own step time over the limit")
            request = wait("a build request", lambda: q("select subject from api.claims where subject like 'urn:kk:request:%%' "
                                                        "and predicate = %s and object_entity = %s", OA + "hasTarget", ANALYSER))[0][0]
            check(q("select lane from api.change_sets where idempotency_key = %s", f"request:{request}")[0][0] == "auto",
                  "request: the planner asks for a better analyser (auto lane: nothing running changes)")
            CANDIDATE = wait("the builder's candidate", lambda: q(
                "select subject from api.claims where predicate = %s and object_entity = %s and attributed_to = 'urn:kk:agent:builder'",
                DCT + "source", request), timeout=1800)[0][0]
            check("experiment:" in git(intent, "log", "--format=%s") and any((intent / "experiments").glob("x*/*/provider.yaml")),
                  f"build: the candidate {CANDIDATE} is committed to intent/experiments/, citing the request")
            queue = wait("the replacement in the review queue", lambda: q(
                "select id, ops from api.review_queue where attributed_to = 'urn:kk:agent:planner'"), timeout=300)
            cs_id, ops = queue[0]
            measures = q("""select s.object_entity, v.qualifiers->>%s, (v.object_value->>'@value')::float from api.claims s
                            join api.claims v on v.subject = s.subject and v.predicate = 'http://www.w3.org/ns/dqv#value'
                            where s.predicate = %s and s.subject like 'urn:kk:eval:sandbox-analyser:%%'""",
                         "http://www.w3.org/ns/dqv#isMeasurementOf", DCT + "subject")
            score = {(p, m.rsplit(":", 1)[-1]): v for p, m, v in measures}
            check(score[(CANDIDATE, "contract.passed")] == score[(CANDIDATE, "contract.total")] == 11
                  and score[(CANDIDATE, "metric.mean")] < score[(ANALYSER, "metric.mean")],
                  f"measure: the candidate passes the analyser contract (11/11) and is faster in the sandbox "
                  f"({score[(CANDIDATE, 'metric.mean')]:.3f} s against {score[(ANALYSER, 'metric.mean')]:.3f} s)")
            check(any(o["predicate"].endswith("substitutedBy") and o["object"] == {"entity": CANDIDATE} for o in ops)
                  and any(o["predicate"] == MAX and o["subject"] == CANDIDATE for o in ops),
                  "plan: run the candidate instead, predicting its step time within the limit; waiting for a person")
            person.execute("select api.review(%s, true, 'measured and better: go ahead')", (cs_id,))
            check(q("select status from api.change_sets where id = %s", cs_id)[0][0] == "applied", "approve: a person approves")
            step = next(o["subject"] for o in ops if o["predicate"].endswith("hasFeatureOfInterest"))
            done = wait("the actuator", lambda: q("select status, cost from kernel.run where agent = 'urn:kk:agent:intent-actuator' "
                                                  "and plan_step = %s and ended_at is not null", step))
            check(done[0][0] == "succeeded" and git(intent, "log", "-1", "--format=%s").startswith(f"change-set:{cs_id}")
                  and CANDIDATE.rsplit(":", 1)[-1] in (intent / "environments" / "sandbox" / "anomaly.yaml").read_text(),
                  "execute: the intent actuator commits the switch to the candidate")
            after = wait("the candidate's own observations", lambda: observed(CANDIDATE))
            check(after, f"the reconciler runs the candidate; its step time is observed (first window {after[0]:.3f} s, "
                         "a warm-up the verifier skips)")
            verdict = wait("a verdict", lambda: q("""select v.subject, t.object_entity from api.claims v join api.claims t on t.subject = v.subject
                                                    where v.subject like 'urn:kk:verdict:%%' and v.predicate = %s and t.predicate = %s""",
                                                 OA + "hasTarget", DCT + "type"), timeout=120)
            said = q("select object_value->>'@value' from api.claims where subject = %s and predicate = %s", verdict[0][0], OA + "bodyValue")[0][0]
            check(verdict[0][1] == "urn:kk:verdict:holds", f"verify: the observed result matches the prediction ({said})")

            # Every step cites the one before it.
            prem = lambda subject: {r[0] for r in q("""select c2.attributed_to from kernel.claim_derivation d
                                                       join api.claims c on c.id = d.claim_id join api.claims c2 on c2.id = d.derived_from
                                                       where c.subject = %s""", subject)}
            plan = next(o["subject"] for o in ops if o["predicate"].endswith("isStepOfPlan"))
            check({"urn:kk:agent:planner", "urn:kk:agent:observer-otel"} <= prem(verdict[0][0]), "the verdict cites the prediction and the observations")
            check({"urn:kk:agent:planner", "urn:kk:agent:evaluator", "urn:kk:agent:builder", PERSON} <= prem(plan),
                  "the plan cites the request, the builder's candidate, the evaluator's scores and the person's limit")
            check({"urn:kk:agent:anomaly", "urn:kk:agent:observer-otel", PERSON} <= prem(request), "the request cites the anomaly, the observation and the limit")
            check(q("select attributed_to from api.claims where subject = %s limit 1", verdict[0][0])[0][0] == "urn:kk:agent:prediction-verifier",
                  "no method verifies its own output: the verdict is the verifier's, not the planner's")
            if os.environ.get("KK_G2_RECORD"):           # the gate run's record: scores, verdict, the candidate built
                out = Path(os.environ["KK_G2_RECORD"])
                out.mkdir(parents=True, exist_ok=True)
                exp = next((intent / "experiments").glob("x*"))
                shutil.copytree(exp, out / exp.name, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
                (out / "run.json").write_text(json.dumps({
                    "builder": builder, "limit_seconds": LIMIT, "incumbent": ANALYSER, "candidate": CANDIDATE,
                    "observed_before": first, "observed_after": observed(CANDIDATE), "verdict_text": said,
                    "sandbox": {k[0].rsplit(":", 1)[-1] + "." + k[1]: v for k, v in score.items()},
                    "verdict": verdict[0][1], "request": request, "plan": plan, "change_set": str(cs_id)}, indent=2) + "\n")
    finally:
        for name, p in reversed(procs):
            p.terminate()
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()
        if os.environ.get("KK_LOOP_LOGS"):
            print(f"logs: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    print("G2 passed")


if __name__ == "__main__":
    main()
