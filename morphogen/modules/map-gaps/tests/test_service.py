"""map-gaps on a live record (R5-29): podinfo's compose file, mapped by encoder-compose, lacks one thing, a limit
on its entry point; the gap finder asks for it, citing the claims that put the frontend on the map; a person's
documented limit closes it (retracted, kept); a pass with nothing changed submits nothing; a service added to
the file without an image is asked about.

  PGHOST=... PGUSER=<superuser> python3 tests/test_service.py
"""
import importlib
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "modules"),
                 str(ROOT / "morphogen" / "modules" / "encoder-compose"), str(ROOT / "kernel" / "providers" / "validator-shacl")]
import install  # noqa: E402  (morphogen/modules/install.py)
from encoder_compose.__main__ import scan  # noqa: E402
from kk.lib import connect, run, submit  # noqa: E402
from map_gaps.__main__ import AGENT, one_pass  # noqa: E402
from map_gaps.gaps import MAX, PROP  # noqa: E402

validator = importlib.import_module("validator.__main__")

DB = "kk_map_gaps_test"
FILE = ROOT / "morphogen" / "intent" / "systems" / "podinfo" / "compose.yaml"
FRONT = "urn:kk:node:podinfo:frontend"
PERSON = "urn:kk:agent:map-gaps-test-person"
OA = "http://www.w3.org/ns/oa#"


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg)


def settle():
    with connect("kkm_validator") as val:
        validator.drain(val)


def gap_pass() -> dict:
    with connect("kkm_map_gaps") as conn:
        res = one_pass(conn)
    settle()
    return res


def open_gaps(conn) -> dict:
    """{target: (kind, question, premises)} of the gap finder's current gaps (one per target is expected)."""
    rows = conn.execute(
        "select t.object_entity, k.object_entity, b.object_value->>'@value', t.id from api.claims t "
        "join api.claims k on k.subject = t.subject and k.predicate = 'http://purl.org/dc/terms/type' and k.status <> 'deprecated' "
        "join api.claims b on b.subject = t.subject and b.predicate = %s and b.status <> 'deprecated' "
        "where t.predicate = %s and t.attributed_to = %s and t.status <> 'deprecated'",
        (OA + "bodyValue", OA + "hasTarget", AGENT)).fetchall()
    out = {}
    for target, kind, text, cid in rows:
        prem = {r[0] for r in conn.execute("select derived_from::text from kernel.claim_derivation where claim_id = %s",
                                           (cid,)).fetchall()}
        out[target] = (kind.rsplit(":", 1)[-1], text, prem)
    return out


subprocess.run(["dropdb", "--if-exists", DB], check=True)
os.environ.setdefault("KK_LOGIN_PASSWORD", secrets.token_hex(16))
install.install(DB, ["encoder-compose", "map-gaps"])
os.environ["DATABASE_URL"] = f"dbname={DB}"
tmp = Path(tempfile.mkdtemp())
try:
    with connect(url=f"dbname={DB}") as su:
        su.execute("do $$ begin if not exists (select 1 from pg_roles where rolname = 't_map_gaps_person') then "
                   "create role t_map_gaps_person nologin; end if; end $$")
        su.execute("grant kk_reviewer to t_map_gaps_person")
        su.execute("set role kk_owner")
        su.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, 't_map_gaps_person', 'person', "
                   "'map-gaps test person') on conflict do nothing", (PERSON,))
    copy = tmp / "systems" / "podinfo" / "compose.yaml"
    copy.parent.mkdir(parents=True)
    shutil.copy(FILE, copy)
    scan("podinfo", copy, tmp)
    settle()
    first = gap_pass()
    with connect("kkm_map_gaps") as conn:
        gaps = open_gaps(conn)
        on_map = {str(r[0]) for r in conn.execute(
            "select id from api.claims where subject = %s and attributed_to = 'urn:kk:agent:encoder-compose' "
            "and predicate in ('http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'https://w3id.org/knowledge-kernel/tosca#memberOf')",
            (FRONT,)).fetchall()}
    check(first["gaps"] == 1 and list(gaps) == [FRONT] and gaps[FRONT][0] == "no-limit",
          f"podinfo as mapped lacks one thing: a limit on its entry point, the frontend ({gaps})")
    check(gaps[FRONT][2] == on_map and "frontend" in gaps[FRONT][1],
          "the gap is a question about the frontend, derived from the claims that put it on the map")
    check(gap_pass()["change_sets"] == {}, "a pass with nothing changed submits nothing")

    with connect("t_map_gaps_person") as person, person.cursor() as cur, run(cur, "urn:kk:module:map-gaps-test") as (run_id, _):
        submit(cur, {"idempotency_key": "map-gaps-test:limit", "attributed_to": PERSON, "target_scope": "urn:kk:scope:default",
                     "ops": [{"op": "add_claim", "subject": FRONT, "predicate": MAX, "object": {"value": {"@value": 0.15}},
                              "qualifiers": {PROP: "urn:kk:property:latency-seconds-mean"}, "evidence_type": "testimony",
                              "references": [{"source_uri": "urn:kk:test:map-gaps#limit"}]}]}, run_id)
    settle()
    second = gap_pass()
    with connect("kkm_map_gaps") as conn:
        left = open_gaps(conn)
        kept = conn.execute("select count(*) from api.claims where attributed_to = %s and status = 'deprecated'",
                            (AGENT,)).fetchone()[0]
    check(second["gaps"] == 0 and second["closed"] == 1 and not left and kept == 4,
          "a person's documented limit closes the gap: its claims are retracted, and kept")

    with connect("t_map_gaps_person") as person, person.cursor() as cur, run(cur, "urn:kk:module:map-gaps-test") as (run_id, _):
        lim = person.execute("select id, status from api.claims where predicate = %s and subject = %s and status <> 'deprecated'",
                             (MAX, FRONT)).fetchone()
        submit(cur, {"idempotency_key": "map-gaps-test:limit-withdrawn", "attributed_to": PERSON, "target_scope": "urn:kk:scope:default",
                     "ops": [{"op": "set_status", "claim": str(lim[0]), "status": "deprecated", "reason": "retracted",
                              "expect_status": lim[1]}]}, run_id)
    settle()
    third = gap_pass()
    with connect("kkm_map_gaps") as conn:
        again = open_gaps(conn)
    check(third["gaps"] == 1 and list(again) == [FRONT] and again[FRONT][0] == "no-limit",
          "a gap that opens again (the limit withdrawn) is asked again")
    check(gap_pass()["change_sets"] == {}, "and stays one open gap: the next pass submits nothing")

    copy.write_text(copy.read_text().replace("services:\n", "services:\n  worker:\n    command: [\"sleep\", \"infinity\"]\n", 1))
    scan("podinfo", copy, tmp)
    settle()
    gap_pass()
    with connect("kkm_map_gaps") as conn:
        now = sorted((t.rsplit(":", 1)[-1], k.rsplit(":", 1)[-1]) for t, k in conn.execute(
            "select t.object_entity, k.object_entity from api.claims t join api.claims k on k.subject = t.subject "
            "and k.predicate = 'http://purl.org/dc/terms/type' and k.status <> 'deprecated' "
            "where t.predicate = %s and t.attributed_to = %s and t.status <> 'deprecated'", (OA + "hasTarget", AGENT)).fetchall())
    check(now == [("frontend", "no-limit"), ("worker", "no-image"), ("worker", "no-limit"), ("worker", "unconnected")],
          f"a service added to the file with no image and no connection is asked about each; the withdrawn limit is still asked ({now})")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
    subprocess.run(["dropdb", "--force", DB], check=True)
print("map-gaps service tests passed")
