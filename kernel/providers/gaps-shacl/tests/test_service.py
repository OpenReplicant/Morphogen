"""The gap finder's service on a live record (R5-47): a small system map, written by a test mapper in kk-tosca terms,
lacks one thing, a limit on its entry point; the service asks for it, citing the claims that put the service on the
map; a person's documented limit closes it (retracted, kept); a pass with nothing changed submits nothing; a gap that
opens again is asked again; a service added without an image or a connection is asked about each.

  PGHOST=... PGUSER=<superuser> python3 tests/test_service.py
"""
import importlib
import os
import secrets
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
KERNEL = HERE.parents[1]
sys.path[:0] = [str(HERE), str(KERNEL / "src"), str(KERNEL / "providers"), str(KERNEL / "providers" / "validator-shacl")]
import install  # noqa: E402  (kernel/providers/install.py)
from gaps_shacl.__main__ import AGENT, one_pass  # noqa: E402
from kk.lib import connect, run, submit  # noqa: E402

validator = importlib.import_module("validator.__main__")

DB = "kk_gaps_shacl_test"
URL = f"dbname={DB}"
KKT = "https://w3id.org/knowledge-kernel/tosca#"
OA = "http://www.w3.org/ns/oa#"
TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
MAX = "https://www.irit.fr/recherches/MELODI/ontologies/BBO#maxValue"
PROP = "http://www.w3.org/ns/sosa/observedProperty"
MAPPER, PERSON = "urn:kk:agent:gaps-test-mapper", "urn:kk:agent:gaps-test-person"
FRONT, BACK, WORKER = "urn:kk:node:shop:front", "urn:kk:node:shop:back", "urn:kk:node:shop:worker"


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg)


def settle():
    with connect("kkm_validator", URL) as val:
        validator.drain(val)


def gap_pass() -> dict:
    with connect("kkm_gaps_shacl", URL) as conn:
        res = one_pass(conn)
    settle()
    return res


def service(name: str, image: bool = True, connects: tuple = ()) -> list[dict]:
    n = f"urn:kk:node:shop:{name}"
    ref = [{"source_uri": "urn:kk:test:gaps-shacl#map"}]
    c = lambda p, o, q=None: {"op": "add_claim", "subject": n, "predicate": p, "object": o,  # noqa: E731
                              "evidence_type": "deterministic", "references": ref, **({"qualifiers": q} if q else {})}
    ops = [c(TYPE, {"entity": KKT + "NodeTemplate"}), c("http://www.w3.org/2000/01/rdf-schema#label", {"value": {"@value": name}}),
           c(KKT + "memberOf", {"entity": "urn:kk:system:shop"})]
    if image:
        ops.append(c(KKT + "propertyValue", {"value": {"@value": f"example/{name}:1@sha256:{'a' * 64}"}}, {KKT + "propertyName": "image"}))
    ops += [c(KKT + "connectsTo", {"entity": f"urn:kk:node:shop:{p}"}) for p in connects]
    return ops


def as_agent(role: str, agent: str, key: str, ops: list[dict]) -> None:
    with connect(role, URL) as conn, conn.cursor() as cur, run(cur, "urn:kk:module:gaps-shacl-test") as (rid, _):
        submit(cur, {"idempotency_key": key, "attributed_to": agent, "target_scope": "urn:kk:scope:default", "ops": ops}, rid)
    settle()


def open_gaps(conn) -> dict:
    """{target: (kind, question, premises)} of the service's current gaps."""
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
        out.setdefault(target, []).append((kind.rsplit(":", 1)[-1], text, prem))
    return out


subprocess.run(["dropdb", "--if-exists", DB], check=True)
os.environ.setdefault("KK_LOGIN_PASSWORD", secrets.token_hex(16))
install.install(DB, ["validator-shacl", "pack-loader", "gaps-shacl"])
os.environ["DATABASE_URL"] = URL
try:
    with connect(url=URL) as su:
        for role, grant in (("t_gaps_mapper", "kk_agent"), ("t_gaps_person", "kk_reviewer")):
            su.execute(f"do $$ begin if not exists (select 1 from pg_roles where rolname = '{role}') then "
                       f"create role {role} nologin; end if; end $$")
            su.execute(f"grant {grant} to {role}")
        su.execute("set role kk_owner")
        su.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, 't_gaps_mapper', 'software', 'mapper'), "
                   "(%s, 't_gaps_person', 'person', 'person') on conflict do nothing", (MAPPER, PERSON))
    as_agent("t_gaps_mapper", MAPPER, "map", service("front", connects=("back",)) + service("back"))
    first = gap_pass()
    with connect("kkm_gaps_shacl", URL) as conn:
        gaps = open_gaps(conn)
        on_map = {str(r[0]) for r in conn.execute(
            "select id from api.claims where subject = %s and predicate in (%s, %s)", (FRONT, TYPE, KKT + "memberOf")).fetchall()}
    check(first["gaps"] == 1 and list(gaps) == [FRONT] and gaps[FRONT][0][0] == "no-limit",
          f"the map lacks one thing: a limit on its entry point, front ({gaps})")
    check(gaps[FRONT][0][2] == on_map and "front" in gaps[FRONT][0][1],
          "the gap is a question about front, derived from the claims that put it on the map, as its shape declares")
    check(gap_pass()["change_sets"] == {}, "a pass with nothing changed submits nothing")

    as_agent("t_gaps_person", PERSON, "limit", [{
        "op": "add_claim", "subject": FRONT, "predicate": MAX, "object": {"value": {"@value": 0.15}},
        "qualifiers": {PROP: "urn:kk:property:latency-seconds-mean"}, "evidence_type": "testimony",
        "references": [{"source_uri": "urn:kk:test:gaps-shacl#limit"}]}])
    second = gap_pass()
    with connect("kkm_gaps_shacl", URL) as conn:
        left = open_gaps(conn)
        kept = conn.execute("select count(*) from api.claims where attributed_to = %s and status = 'deprecated'",
                            (AGENT,)).fetchone()[0]
    check(second["gaps"] == 0 and second["closed"] == 1 and not left and kept == 4,
          "a person's documented limit closes the gap: its claims are retracted, and kept")

    with connect("t_gaps_person", URL) as person:
        lim = person.execute("select id, status from api.claims where predicate = %s and subject = %s and status <> 'deprecated'",
                             (MAX, FRONT)).fetchone()
    as_agent("t_gaps_person", PERSON, "limit-withdrawn", [{"op": "set_status", "claim": str(lim[0]), "status": "deprecated",
                                                           "reason": "retracted", "expect_status": lim[1]}])
    third = gap_pass()
    with connect("kkm_gaps_shacl", URL) as conn:
        again = open_gaps(conn)
    check(third["gaps"] == 1 and list(again) == [FRONT], "a gap that opens again (the limit withdrawn) is asked again")
    check(gap_pass()["change_sets"] == {}, "and stays one open gap: the next pass submits nothing")

    as_agent("t_gaps_mapper", MAPPER, "worker", service("worker", image=False))
    gap_pass()
    with connect("kkm_gaps_shacl", URL) as conn:
        now = sorted((t.rsplit(":", 1)[-1], k) for t, gs in open_gaps(conn).items() for k, _, _ in gs)
    check(now == [("front", "no-limit"), ("worker", "no-image"), ("worker", "no-limit"), ("worker", "unconnected")],
          f"a service added with no image and no connection is asked about each ({now})")
finally:
    subprocess.run(["dropdb", "--force", DB], check=True)
print("gaps-shacl service tests passed")
