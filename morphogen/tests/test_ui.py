"""T21: the review and loop UI, through its server and a browser (headless Chromium, Node Playwright).

A planner's plan waits in the review lane, inferred from an anomaly and an observation; a person signs in with
their own login, sees the plan (label, risk, step, prediction) and the claims it cites with their belief, and
approves it: the store records the approval as theirs, under their own role. The loop lists the anomaly; the
systems view draws the mapped system. A wrong password, a login that is not a person's, a person who is not a
reviewer and a person's login that also holds an agent's role are all refused; a token is required for every MCP
call; a person cannot approve their own change set; a person removed (people.py remove) is refused at once.

  PGHOST=... PGUSER=<superuser> python3 morphogen/tests/test_ui.py     (needs node with playwright)
"""
import importlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "modules"), str(ROOT / "morphogen" / "ui"),
                str(ROOT / "morphogen" / "modules" / "planner"),
                str(ROOT / "morphogen" / "modules" / "prediction-verifier"), str(ROOT / "kernel" / "providers" / "validator-shacl"),
                str(ROOT / "kernel" / "providers" / "belief-corroboration"), str(ROOT / "kernel" / "providers" / "self-encoder")]
import install  # noqa: E402  (morphogen/modules/install.py)
import people  # noqa: E402
from kk import mappings  # noqa: E402
from kk.lib import connect, follow, run, submit  # noqa: E402
from planner.plan import change_set  # noqa: E402
from prediction_verifier import verify  # noqa: E402

validator = importlib.import_module("validator.__main__")
belief = importlib.import_module("belief_corroboration.__main__")
self_encoder = importlib.import_module("self_encoder.__main__")

DB = "kk_ui_test"
URL = f"dbname={DB}"
PLANNER, SEED = "urn:kk:agent:ui-test-planner", "urn:kk:agent:ui-test-observer"
ACTUATOR, VERIFIER = "urn:kk:agent:ui-test-actuator", "urn:kk:agent:ui-test-verifier"
SOSA, OA, KKT = "http://www.w3.org/ns/sosa/", "http://www.w3.org/ns/oa#", "https://w3id.org/knowledge-kernel/tosca#"
RDF_TYPE, DCT_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "http://purl.org/dc/terms/type"
NODE = "urn:kk:node:shop:web"
SKOS = "http://www.w3.org/2004/02/skos/core#"


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg)


def settle():
    with connect("kkm_validator", URL) as val:
        validator.drain(val)


def record(role, agent, key, ops, lane=None):
    with connect(role, URL) as conn, conn.cursor() as cur, run(cur, "urn:kk:module:ui-test") as (rid, _):
        res = submit(cur, {"idempotency_key": key, "attributed_to": agent, "target_scope": "urn:kk:scope:default",
                           "ops": ops, **({"lane": lane} if lane else {})}, rid)
    settle()
    return res


def claim(s, p, o, **kw):
    return {"op": "add_claim", "subject": s, "predicate": p, "object": o, "evidence_type": kw.pop("evidence", "observed"),
            "references": [{"source_uri": "urn:test:ui"}], **kw}


def post(url, body, token=None):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json",
                                 "Accept": "application/json, text/event-stream",
                                 **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


subprocess.run(["dropdb", "--if-exists", "--force", DB], check=True)
install.install(DB, ["lane-autonomy", "planner"])
install.kernel.install(DB, ["self-encoder"])
password, secret = secrets.token_urlsafe(18), secrets.token_urlsafe(40)
auth_pw = secrets.token_urlsafe(18)
with connect(url=URL) as su:
    for r in ("t_ui_planner", "t_ui_observer", "t_ui_actuator", "t_ui_verifier"):
        su.execute(f"do $$ begin if not exists (select 1 from pg_roles where rolname = '{r}') then create role {r} nologin; "
                   f"end if; end $$")
        su.execute(f"grant kk_agent to {r}")
    su.execute("set role kk_owner")
    su.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, 't_ui_planner', 'software', 'planner'), "
               "(%s, 't_ui_observer', 'software', 'observer'), (%s, 't_ui_actuator', 'software', 'actuator'), "
               "(%s, 't_ui_verifier', 'software', 'verifier') on conflict do nothing", (PLANNER, SEED, ACTUATOR, VERIFIER))
    su.execute("reset role")
    alice = people.add(su, "alice", password, "Alice")
    people.add(su, "eve", password, "Eve")
    su.execute("revoke kk_reviewer from person_eve")                  # a person who is not a reviewer
    people.add(su, "mallory", password, "Mallory")
    su.execute("grant kkm_planner to person_mallory")                 # a person's login that can act as the planner
    from psycopg import sql
    verifier = su.pgconn.encrypt_password(auth_pw.encode(), b"kk_authenticator", b"scram-sha-256").decode()
    su.execute(sql.SQL("alter role kk_authenticator password {}").format(sql.Literal(verifier)))
    su.execute(f'grant connect on database "{DB}" to kk_authenticator, person_alice, person_eve, person_mallory')

# What Morphogen is made of, as the overview reads it: the kernel's blueprint, every provider and the distribution.
os.environ["DATABASE_URL"] = URL
scanned = self_encoder.scan(ROOT, [str(ROOT / "morphogen" / "distribution.yaml")], [], [str(ROOT / "morphogen" / "modules")])
check(all(r.get("status") in ("submitted", "applied", "unchanged") for r in scanned), "the self-encoder records the slots and providers")
settle()

# A small system's map, an observation over its limit, the anomaly on it, and the planner's plan in the review lane.
record("t_ui_observer", SEED, "map", [
    claim("urn:kk:system:shop", RDF_TYPE, {"entity": KKT + "ServiceTemplate"}, evidence="deterministic"),
    claim(NODE, RDF_TYPE, {"entity": KKT + "NodeTemplate"}, evidence="deterministic"),
    claim(NODE, KKT + "memberOf", {"entity": "urn:kk:system:shop"}, evidence="deterministic"),
    claim("urn:kk:node:shop:db", KKT + "memberOf", {"entity": "urn:kk:system:shop"}, evidence="deterministic"),
    claim(NODE, KKT + "connectsTo", {"entity": "urn:kk:node:shop:db"}, evidence="deterministic"),
    claim(NODE, SOSA + "hasSimpleResult", {"value": {"@value": 0.31}}, qualifiers={SOSA + "observedProperty": "urn:kk:property:latency-seconds-mean"},
          valid_from="2026-10-24T10:00:00+00:00", valid_to="2026-10-24T10:01:00+00:00")])
with connect(url=URL) as su:
    obs = str(su.execute("select id from kernel.claim where predicate = %s", (SOSA + "hasSimpleResult",)).fetchone()[0])
record("t_ui_observer", SEED, "anomaly", [
    claim("urn:kk:anomaly:a1", RDF_TYPE, {"entity": OA + "Annotation"}, evidence="inferred", derived_from=[obs]),
    claim("urn:kk:anomaly:a1", DCT_TYPE, {"entity": "urn:kk:anomaly-kind:limit"}, evidence="inferred", derived_from=[obs]),
    claim("urn:kk:anomaly:a1", OA + "hasTarget", {"entity": NODE}, evidence="inferred", derived_from=[obs]),
    claim("urn:kk:anomaly:a1", OA + "bodyValue", {"value": {"@value": "web: latency 0.31 exceeds the limit 0.2."}},
          evidence="inferred", derived_from=[obs])])
with connect("kkm_belief", URL) as bel:          # the belief service scores what was recorded
    follow(bel, belief.Pass(), once=True)
settle()
with connect(url=URL) as su:
    premises = sorted({obs} | {str(r[0]) for r in su.execute("select id from kernel.claim where subject = 'urn:kk:anomaly:a1'")})
plan = {"iri": "urn:kk:plan:ui1", "step": "urn:kk:plan:ui1:step:1", "label": "Lower web's worker delay to 50 ms",
        "risk": "medium", "action": "urn:kk:action:set-setting", "target": "urn:kk:setting:shop:web:DELAY", "to": 50,
        "observed": NODE, "property": "urn:kk:property:latency-seconds-mean", "limit": 0.2, "premises": premises}
cs = record("t_ui_planner", PLANNER, "plan:ui1", change_set(plan, PLANNER, "urn:kk:scope:default", "review")["ops"], lane="review")
with connect(url=URL) as su:
    status = su.execute("select status from kernel.change_set where id = %s", (cs["id"],)).fetchone()[0]
check(status == "awaiting_review", f"the plan waits for a person in the review lane ({status})")

port = (lambda s: (s.bind(("127.0.0.1", 0)), s.getsockname()[1], s.close())[1])(socket.socket())
host, pgport = os.environ.get("PGHOST", "localhost"), os.environ.get("PGPORT", "5432")
env = {**os.environ, "DATABASE_URL": f"host={host} port={pgport} dbname={DB} user=kk_authenticator password={auth_pw}",
       "KK_JWT_SECRET": secret, "PORT": str(port)}
for k in ("PGUSER", "PGPASSWORD"):
    env.pop(k, None)
log = open(Path(os.environ.get("TMPDIR", "/tmp")) / "kk_ui_test.log", "w")
server = subprocess.Popen([sys.executable, str(ROOT / "morphogen" / "ui" / "serve.py")], env=env, stdout=log, stderr=subprocess.STDOUT)
base = f"http://127.0.0.1:{port}"
try:
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/ui/", timeout=2)
            break
        except OSError:
            time.sleep(0.2)
    else:
        sys.exit("FAIL: the UI server did not start")

    # Sign-in: only a person, with their own password, who reviews.
    code, body = post(base + "/ui/login", {"name": "alice", "password": "not her password"})
    check(code == 401, "a wrong password is refused")
    code, body = post(base + "/ui/login", {"name": "eve", "password": password})
    check(code == 401, "a person who is not a reviewer is refused")
    code, body = post(base + "/ui/login", {"name": "authenticator", "password": auth_pw})
    check(code == 401, "a login that is not a person's is refused")
    code, body = post(base + "/ui/login", {"name": "mallory", "password": password})
    check(code == 401, "a person's login that can also act as an agent (the planner) is refused")
    code, body = post(base + "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                      "params": {"name": "review_queue", "arguments": {}}})
    check(code != 200 or (body.get("result") or {}).get("isError"), "an MCP call without a token is refused")

    # The browser: sign in, read the plan and what it cites, approve; the loop and the system map.
    out = subprocess.run(["node", str(ROOT / "morphogen" / "tests" / "ui_browser.js")], capture_output=True, text=True,
                         timeout=300, env={**os.environ, "UI": base + "/ui/", "NAME": "alice", "PASSWORD": password,
                                           "PLAN": plan["label"], **({"SHOT": os.environ["KK_UI_SHOT"]} if os.environ.get("KK_UI_SHOT") else {})})
    print(out.stdout.strip())
    check(out.returncode == 0, f"the browser run passes ({out.stderr.strip()[-800:]})")
    seen = json.loads(out.stdout.strip().splitlines()[-1])
    check(seen["agent"] == alice, "signed in, the page shows the person's own agent")
    check(seen["prediction"] and "0.2" in seen["prediction"], f"the plan shows its prediction ({seen['prediction']})")
    check(len(seen["cited"]) == len(premises) and all(b not in ("", "—") for _, b in seen["cited"]),
          f"the plan shows every claim it cites with its belief ({len(seen['cited'])} of {len(premises)})")
    check(seen["after"] == 0, "after approving, nothing waits for review")
    check(any("exceeds the limit" in t for t in seen["loop"]), "the loop lists the anomaly")
    check(int(seen["nodes"]) >= 3, f"the systems view draws the mapped system ({seen['nodes']} nodes)")
    import yaml
    declared = len(yaml.safe_load((ROOT / "kernel" / "blueprint" / "slots.yaml").read_text())["slots"]) + \
        len(yaml.safe_load((ROOT / "morphogen" / "distribution.yaml").read_text())["slots"])
    check(seen["slots"] == declared and seen["tiles"]["slots"].endswith(f"/ {declared}"),
          f"the overview shows every slot of the kernel and of Morphogen ({seen['slots']} of {declared}, {seen['tiles']})")
    check(seen["gapFinder"] == ["gaps-shacl"], f"each slot names its default provider ({seen['gapFinder']})")
    check(sorted(seen["runtime"]["providers"]) == ["runtime-compose", "runtime-quadlet"] and seen["runtime"]["defaults"] == ["runtime-compose"],
          f"a slot opens with every provider that fills it, its default marked ({seen['runtime']})")
    check(seen["runtime"]["where"].startswith("morphogen/distribution.yaml line "),
          f"and where its default is written, from the claim's own reference ({seen['runtime']['where']})")
    check(seen["tiles"]["review"] == "1" and seen["tiles"]["systems"] == "1", f"the tiles count what waits and what is mapped ({seen['tiles']})")
    with connect(url=URL) as su:
        st, by = su.execute("select status, decided_by from kernel.change_set where id = %s", (cs["id"],)).fetchone()
    check(st in ("approved", "applied") and by == "person_alice", f"the store records the approval as Alice's own ({st}, {by})")

    # Carried out and checked: the actuator's run for the step, then the verifier's verdict on the prediction.
    # The loop shows the plan with who approved it, its run and its verdict, and the verdict explains itself.
    with connect("t_ui_actuator", URL) as conn, conn.cursor() as cur, \
            run(cur, "urn:kk:module:ui-test-actuator", {"plan": plan["iri"]}, plan_step=plan["step"]):
        pass
    record("t_ui_observer", SEED, "after", [
        claim(NODE, SOSA + "hasSimpleResult", {"value": {"@value": 0.12}}, qualifiers={SOSA + "observedProperty": plan["property"]},
              valid_from="2026-10-24T10:05:00+00:00", valid_to="2026-10-24T10:06:00+00:00")])
    with connect(url=URL) as su:
        pred = str(su.execute("select id from kernel.claim where predicate = %s and qualifiers ? %s",
                              (verify.MAX, verify.PART_OF)).fetchone()[0])
        after = str(su.execute("select id from kernel.claim where predicate = %s and valid_from = '2026-10-24T10:05:00+00:00'",
                               (SOSA + "hasSimpleResult",)).fetchone()[0])
    v = {"verdict": "holds", "premises": [pred, after], "text": "latency-seconds-mean was 0.12 after the change: within the predicted limit 0.2."}
    vcs = verify.change_set({"id": pred}, plan["iri"], v, VERIFIER, "urn:kk:scope:default")
    record("t_ui_verifier", VERIFIER, vcs["idempotency_key"], vcs["ops"])
    with connect("kkm_belief", URL) as bel:
        follow(bel, belief.Pass(), once=True)
    settle()
    out = subprocess.run(["node", str(ROOT / "morphogen" / "tests" / "ui_browser.js")], capture_output=True, text=True,
                         timeout=300, env={**os.environ, "UI": base + "/ui/", "NAME": "alice", "PASSWORD": password,
                                           "PLAN": plan["label"], "STEP": "plans",
                                           **({"SHOT": os.environ["KK_UI_SHOT_PLANS"]} if os.environ.get("KK_UI_SHOT_PLANS") else {})})
    print(out.stdout.strip())
    check(out.returncode == 0, f"the plans view loads ({out.stderr.strip()[-800:]})")
    row = json.loads(out.stdout.strip().splitlines()[-1])
    check("person_alice" in row["decided"] and row["decided"].startswith(("approved", "applied")),
          f"the plan shows who approved it ({row['decided']})")
    check(row["run"].startswith("succeeded by ui-test-actuator"), f"the plan shows its step was carried out, and by whom ({row['run']})")
    check(row["verdict"].startswith("holds") and "0.12" in row["verdict"] and "(belief 0." in row["verdict"],
          f"the plan shows its verdict and the verdict's belief ({row['verdict']})")
    check(set(row["detail"]["derived_from"]) == {pred, after}, "the verdict explains itself: the prediction and the observation")

    # The vocabularies: every pack, the mappings readers follow and one software proposed, waiting for a person (R5-51);
    # a term shows who writes and reads it (the providers' declared lines) and its mappings, each opening its claim.
    # Two more a person approved: a relatedMatch (accepted, never followed) and one a steward then redacts (gone).
    approved = record("t_ui_planner", PLANNER, "mappings-approved", [
        claim("https://example.org/ns#Task", SKOS + "relatedMatch", {"entity": "http://purl.org/net/p-plan#Step"}, evidence="deterministic"),
        claim("https://example.org/ns#Gone", SKOS + "exactMatch", {"entity": "http://www.w3.org/ns/prov#Activity"}, evidence="deterministic")])
    with connect("person_alice", URL) as person:
        person.execute("select api.review(%s, true, 'test: mappings')", (approved["id"],))
    with connect(url=URL) as su:
        su.execute("do $$ begin if not exists (select 1 from pg_roles where rolname = 't_ui_steward') then create role t_ui_steward nologin; "
                   "end if; end $$")
        su.execute("grant kk_agent, kk_steward to t_ui_steward")
        su.execute("set role kk_owner")
        su.execute("insert into kernel.agent(iri, db_role, kind, label) values ('urn:kk:agent:ui-test-steward', 't_ui_steward', "
                   "'person', 'steward') on conflict do nothing")
        gone = str(su.execute("select id from api.claims where subject = 'https://example.org/ns#Gone'").fetchone()[0])
    with connect("t_ui_steward", URL) as st, st.cursor() as cur, run(cur, None) as (rid, _):
        cur.execute("select api.redact('claim', %s, 'test erasure', %s)", (gone, rid))
    proposed = record("t_ui_planner", PLANNER, "mapping", [
        claim("https://example.org/ns#Job", SKOS + "broadMatch", {"entity": "http://purl.org/net/p-plan#Step"}, evidence="deterministic",
              qualifiers={"https://w3id.org/sssom/mapping_justification": "https://w3id.org/semapv/vocab/ManualMappingCuration"})])
    out = subprocess.run(["node", str(ROOT / "morphogen" / "tests" / "ui_browser.js")], capture_output=True, text=True,
                         timeout=300, env={**os.environ, "UI": base + "/ui/", "NAME": "alice", "PASSWORD": password, "STEP": "vocab",
                                           **({"SHOT": os.environ["KK_UI_SHOT_VOCAB"]} if os.environ.get("KK_UI_SHOT_VOCAB") else {})})
    check(out.returncode == 0, f"the vocabularies view loads ({out.stderr.strip()[-800:]})")
    seen = json.loads(out.stdout.strip().splitlines()[-1])
    with connect(url=URL) as su:
        ontologies = su.execute("select count(*) from api.claims where predicate = %s and object_entity = %s",
                                (RDF_TYPE, "http://www.w3.org/2002/07/owl#Ontology")).fetchone()[0]
        mapping, mapping_belief = su.execute("select id::text, belief from api.claims where subject = 'http://www.w3.org/ns/sosa/Observation' "
                                             "and predicate = %s and object_entity = 'http://www.w3.org/ns/prov#Activity'",
                                             (SKOS + "broadMatch",)).fetchone()
        followed = su.execute(mappings.CURRENT, {"matches": [p for p in mappings.MATCHES if p != mappings.RELATED]}).fetchall()
    check(len(seen["packs"]) == ontologies and any(p.startswith("SSSOM") for p in seen["packs"]),
          f"the view lists every vocabulary in the record ({len(seen['packs'])} of {ontologies})")
    check(["Observation", "is narrower than", "Activity"] == next((r[:3] for r in seen["rows"] if r[0] == "Observation"), None),
          "a pack's mapping reads left to right: Observation is narrower than Activity")
    obs = next(r for r in seen["rows"] if r[0] == "Observation")
    check(obs[4] == f"{float(mapping_belief):.2f}", f"a followed mapping shows its claim's belief ({obs[4]}, {mapping_belief})")
    check(seen["followed"] == str(len(followed)) and not any(r[0] == "Gone" for r in seen["rows"]),
          f"the followed count is what readers follow (kk.mappings), and a redacted mapping is gone ({seen['followed']} of {len(followed)})")
    related = [r for r in seen["rows"] if r[0] == "Task"]
    check(len(related) == 1 and related[0][1] == "is related to" and "not followed" in related[0][5],
          f"an approved relatedMatch shows as accepted but not followed ({related})")
    waiting = [r for r in seen["rows"] if r[0] == "Job"]
    check(proposed["status"] in ("submitted", "valid") and seen["pending"] == "1" and len(waiting) == 1
          and waiting[0][1] == "is narrower than" and "waiting for review" in waiting[0][5] and "ManualMappingCuration" in waiting[0][3]
          and waiting[0][4] == "—",
          f"a mapping software proposed shows as waiting for review, never as followed ({waiting}, {seen['pending']})")
    check("observer-otel" in seen["result"]["writers"] and "anomaly" in seen["result"]["readers"],
          f"a term shows who writes it and who reads it ({seen['result']})")
    check({"is narrower than Activity", "QualityMeasurement is narrower than this"} == set(seen["observation"]["mappings"])
          and seen["detail"]["claim"]["id"] == mapping,
          f"a term shows its mappings, and a mapping opens its own claim ({seen['observation']['mappings']})")

    # Alice proposes a change herself (a person is an agent too): the store refuses her approving it.
    code, body = post(base + "/ui/login", {"name": "alice", "password": password})
    token = body["token"]

    def tool(name, args):
        return post(base + "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                    "params": {"name": name, "arguments": args}}, token)[1]["result"]
    rid = (tool("start_run", {})["structuredContent"] or {}).get("result")
    mine = tool("submit_change_set", {"change_set": {
        "idempotency_key": "ui:alice-own", "attributed_to": alice, "generated_by": rid, "target_scope": "urn:kk:scope:default",
        "lane": "review", "ops": [claim("urn:kk:node:shop:web", "http://www.w3.org/2000/01/rdf-schema#comment",
                                        {"value": {"@value": "Alice thinks web is slow."}}, evidence="testimony")]}})
    mine_id = json.loads(mine["content"][0]["text"])["id"] if not mine.get("structuredContent") else mine["structuredContent"].get("result", mine["structuredContent"])["id"]
    tool("finish_run", {"run_id": rid})
    settle()
    own = tool("review", {"change_set_id": mine_id, "approve": True})
    check(own.get("isError"), f"Alice cannot approve her own change set ({own['content'][0]['text'][:120]})")

    # Removed, Alice's token stops working at once.
    with connect(url=URL) as su:
        people.remove(su, "alice")
    gone = tool("whoami", {})
    check(gone.get("isError"), "a person removed is refused on their next call")
    code, body = post(base + "/ui/login", {"name": "alice", "password": password})
    check(code == 401, "and cannot sign in again")
finally:
    server.terminate()
    server.wait(timeout=10)
subprocess.run(["dropdb", "--if-exists", "--force", DB], check=True)
print("UI checks passed")
