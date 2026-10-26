"""Query-time mappings (kk.mappings, R5-51): which terms a question about a term counts, and the mapping claims
each rests on. Pure checks first (directions, transitivity, closeMatch at most once, relatedMatch never), then
over a record: a pack's mapping is followed; a proposed one is not until a person approves it; a retracted or
redacted one is no longer followed.

  PGHOST=... PGUSER=<superuser> python3 kernel/providers/tests/test_mappings.py
"""
import importlib
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROVIDERS = HERE.parent
for p in (PROVIDERS.parent / "src", PROVIDERS / "validator-shacl", PROVIDERS):
    sys.path.insert(0, str(p))

from kk import mappings as m  # noqa: E402
from kk.lib import connect, run, submit  # noqa: E402
import install  # noqa: E402

validator = importlib.import_module("validator.__main__")

DB = "kk_mappings_test"
SOSA, PROV = "http://www.w3.org/ns/sosa/", "http://www.w3.org/ns/prov#"
WRITER, PERSON, STEWARD = "urn:kk:agent:test-mapper", "urn:kk:agent:test-reviewer", "urn:kk:agent:test-steward"


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def pure() -> None:
    rows = [("a", m.EXACT, "b", "1"), ("c", m.EXACT, "b", "2"),          # a = b = c
            ("n", m.BROAD, "a", "3"), ("nn", m.BROAD, "n", "4"),         # nn < n < a
            ("a", m.NARROW, "k", "5"),                                   # k < a
            ("a", m.CLOSE, "x", "6"), ("x", m.CLOSE, "y", "7"),          # a ~ x ~ y
            ("a", m.RELATED, "r", "8")]
    got = m.reach(rows, "a")
    check(got == {"a": [], "b": ["1"], "c": ["1", "2"], "n": ["3"], "nn": ["3", "4"], "k": ["5"], "x": ["6"]},
          f"from a: exact both ways and on, narrower terms and theirs, one closeMatch, never relatedMatch ({got})")
    check(set(m.reach(rows, "nn")) == {"nn"}, "a question about the narrowest term never counts a broader one")
    check(set(m.reach(rows, "c")) == {"a", "b", "c", "n", "nn", "k", "x"}, "exactMatch is followed backwards too")
    check(m.reach(rows, "y") == {"y": [], "x": ["7"]}, "closeMatch is not chained: y reaches x, not a")
    check(m.reach([("a", m.EXACT, "b", "9"), ("a", m.EXACT, "b", "1")], "a") == {"a": [], "b": ["1"]},
          "ties break the same way every time")


def main() -> None:
    pure()
    subprocess.run(["dropdb", "--if-exists", DB], check=True)
    install.install(DB, ["validator-shacl", "pack-loader"])
    url = f"dbname={DB}"
    with connect(url=url) as su:
        for role in ("t_map_writer", "t_map_person", "t_map_steward"):
            su.execute(f"do $$ begin if not exists (select 1 from pg_roles where rolname = '{role}') then "
                       f"create role {role} nologin; end if; end $$")
            su.execute(f"grant kk_agent to {role}")
        su.execute("grant kk_reviewer to t_map_person")
        su.execute("grant kk_steward to t_map_steward")
        su.execute("set role kk_owner")
        su.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, 't_map_writer', 'software', 'w'), "
                   "(%s, 't_map_person', 'person', 'p'), (%s, 't_map_steward', 'person', 's') on conflict do nothing",
                   (WRITER, PERSON, STEWARD))

    def match(s, p, o):
        return {"op": "add_claim", "subject": s, "predicate": p, "object": {"entity": o},
                "evidence_type": "deterministic", "references": [{"source_uri": "urn:test:mappings"}]}

    with connect("t_map_writer", url) as w, connect("t_map_person", url) as person, \
            connect("t_map_steward", url) as st, connect("kkm_validator", url) as val:
        def asked():
            with w.cursor() as cur:
                return m.equivalents(cur, PROV + "Activity")

        got = asked()
        pack = w.execute("select id::text from api.claims where subject = %s and predicate = %s and object_entity = %s",
                         (SOSA + "Observation", m.BROAD, PROV + "Activity")).fetchone()[0]
        check(got.get(SOSA + "Observation") == [pack], "a pack's mapping is followed, citing its claim")

        with w.cursor() as cur, run(cur, "urn:kk:module:test-map") as (rid, _):
            cs = submit(cur, {"idempotency_key": "propose", "attributed_to": WRITER, "target_scope": "urn:kk:scope:vocab",
                              "ops": [match("urn:x:Job", m.BROAD, PROV + "Activity")]}, rid)
        validator.drain(val)
        status = w.execute("select status from api.change_sets where id = %s", (cs["id"],)).fetchone()[0]
        check(status == "awaiting_review" and "urn:x:Job" not in asked(),
              f"a proposed mapping waits for review and is not followed ({status})")
        person.execute("select api.review(%s, true, 'a job is an activity')", (cs["id"],))
        job = w.execute("select id::text from api.claims where subject = 'urn:x:Job'").fetchone()[0]
        check(asked().get("urn:x:Job") == [job], "once a person approves it, it is followed and cited")

        with w.cursor() as cur, run(cur, "urn:kk:module:test-map") as (rid, _):
            drop = submit(cur, {"idempotency_key": "retract", "attributed_to": WRITER, "target_scope": "urn:kk:scope:vocab",
                                "ops": [{"op": "set_status", "claim": job, "status": "deprecated", "expect_status": "normal",
                                         "reason": "retracted"}]}, rid)
        validator.drain(val)
        status = w.execute("select status from api.change_sets where id = %s", (drop["id"],)).fetchone()[0]
        check(status == "awaiting_review" and "urn:x:Job" in asked(),
              f"retracting an approved mapping waits for a person too, and it is followed until then ({status})")
        person.execute("select api.review(%s, true, 'no longer right')", (drop["id"],))
        check("urn:x:Job" not in asked(), "a retracted mapping is no longer followed")
        with st.cursor() as cur, run(cur, None) as (rid, _):
            cur.execute("select api.redact('claim', %s, 'test erasure', %s)", (pack, rid))
        check(SOSA + "Observation" not in asked(), "a redacted mapping is no longer followed")
    subprocess.run(["dropdb", "--if-exists", DB], check=True)
    print("mapping checks passed")


if __name__ == "__main__":
    main()
