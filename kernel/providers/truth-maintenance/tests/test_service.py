"""Truth maintenance against a live record (rebuild 4 D-89): a claim inferred from a premise, and one inferred from
that, are flagged inconclusive when the premise is retracted, naming it; a claim on a current premise is left
alone; a second pass submits nothing; the belief model then caps the flagged claims; restored, they are
supported (the cap lifts), and withdrawn again, flagged again; a premise superseded by a new claim, even with the
same value (R5-31), or redacted, undermines what was built on it; a verdict goes to its claim's own scope.

  PGHOST=... PGUSER=<superuser> python3 tests/test_service.py
"""
import importlib
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PROVIDERS = HERE.parent
for p in (PROVIDERS.parent / "src", PROVIDERS / "validator-shacl", PROVIDERS / "belief-corroboration", PROVIDERS, HERE):
    sys.path.insert(0, str(p))

from kk.lib import connect, follow, run, submit  # noqa: E402
import install  # noqa: E402

validator = importlib.import_module("validator.__main__")
belief = importlib.import_module("belief_corroboration.__main__")
tms = importlib.import_module("truth_maintenance.__main__")
from belief_corroboration.model import PREMISE_CAP  # noqa: E402

DB = "kk_tms_test"
EXTRACTOR = "urn:kk:agent:test-extractor"
SCOPE = "urn:kk:scope:default"


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def main() -> None:
    subprocess.run(["dropdb", "--if-exists", DB], check=True)
    install.install(DB, ["validator-shacl", "belief-corroboration", "truth-maintenance"])
    url = f"dbname={DB}"
    with connect(url=url) as su:
        su.execute("do $$ begin if not exists (select 1 from pg_roles where rolname = 't_tms_extractor') then "
                   "create role t_tms_extractor nologin; end if; end $$")
        su.execute("do $$ begin if not exists (select 1 from pg_roles where rolname = 't_tms_steward') then "
                   "create role t_tms_steward nologin; end if; end $$")
        su.execute("grant kk_agent to t_tms_extractor")
        su.execute("grant kk_steward to t_tms_steward")
        su.execute("set role kk_owner")
        su.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, 't_tms_extractor', "
                   "'software', 'Test extractor'), ('urn:kk:agent:test-steward', 't_tms_steward', 'person', "
                   "'Test steward') on conflict do nothing", (EXTRACTOR,))

    with connect("t_tms_extractor", url) as ex, connect("kkm_validator", url) as val, \
            connect("kkm_truth_maintenance", url) as tm, connect("kkm_belief", url) as bel, \
            connect("t_tms_steward", url) as st:
        def cs(key, ops, scope=SCOPE):
            with ex.cursor() as cur, run(cur, "urn:kk:module:test-extractor") as (run_id, _):
                got = submit(cur, {"idempotency_key": key, "attributed_to": EXTRACTOR, "target_scope": scope, "ops": ops}, run_id)
            validator.drain(val)
            return got

        def claim_id(subject, predicate="rdfs:label"):
            return str(ex.execute("select id from api.claims where subject = %s and status <> 'deprecated' and predicate = "
                                  "(select kernel.expand(%s))", (subject, predicate)).fetchone()[0])

        def fact(s, v, ref):
            return {"op": "add_claim", "subject": s, "predicate": "rdfs:label", "object": {"value": {"@value": v}},
                    "evidence_type": "testimony", "references": [{"source_uri": ref}]}

        def inferred(s, v, premises):
            return {"op": "add_claim", "subject": s, "predicate": "rdfs:label", "object": {"value": {"@value": v}},
                    "evidence_type": "inferred", "derived_from": premises}

        cs("tms:premises", [fact("urn:x:p", "premise", "urn:test:p"), fact("urn:x:q", "other premise", "urn:test:q")])
        p, q = claim_id("urn:x:p"), claim_id("urn:x:q")
        cs("tms:c", [inferred("urn:x:c", "from p", [p]), inferred("urn:x:e", "from q", [q])])
        c, e = claim_id("urn:x:c"), claim_id("urn:x:e")
        cs("tms:d", [inferred("urn:x:d", "from c", [c])])
        d = claim_id("urn:x:d")

        follow(tm, tms.step, once=True)
        check(validator.drain(val) == 0, "nothing withdrawn: truth maintenance submits nothing")

        cs("tms:retract-p", [{"op": "set_status", "claim": p, "status": "deprecated", "expect_status": "normal",
                              "reason": "retracted"}])
        follow(tm, tms.step, once=True)
        check(validator.drain(val) == 1, "a premise retracted: one change set of verdicts")
        got = {str(r[0]): (r[1], r[2]) for r in ex.execute(
            "select claim_id, verdict, details from api.verifications where method = %s", (tms.METHOD,)).fetchall()}
        check(got.get(c, (None,))[0] == "inconclusive" and got[c][1]["withdrawn"] == [p],
              "the claim inferred from it is inconclusive, naming the withdrawn premise")
        check(got.get(d, (None,))[0] == "inconclusive" and got[d][1]["withdrawn"] == [p],
              "a claim inferred from that claim is flagged too, through the chain")
        check(e not in got and p not in got, "a claim on a current premise, and the withdrawn claim itself, are left alone")
        follow(tm, tms.step, once=True)
        check(validator.drain(val) == 0, "a second pass submits nothing")

        follow(bel, belief.Pass(), once=True)
        validator.drain(val)
        b = dict((str(i), v) for i, v in ex.execute("select id, belief from api.claims where id = any(%s::uuid[])",
                                                    ([c, d, e],)).fetchall())
        check(b[c] is not None and b[c] <= PREMISE_CAP and b[d] <= PREMISE_CAP,
              f"the belief model caps the flagged claims at {PREMISE_CAP} ({b[c]}, {b[d]})")

        def latest(claim):
            row = ex.execute("select verdict from api.verifications where method = %s and claim_id = %s "
                             "order by recorded_at desc limit 1", (tms.METHOD, claim)).fetchone()
            return row and row[0]

        # Restored: the premise current again, what was built on it is supported and the cap lifts; withdrawn
        # again, flagged again.
        cs("tms:restore-p", [{"op": "set_status", "claim": p, "status": "normal", "expect_status": "deprecated"}])
        follow(tm, tms.step, once=True)
        validator.drain(val)
        check(latest(c) == "supported" and latest(d) == "supported", "the premise current again: the claims built on it are supported")
        follow(bel, belief.Pass(), once=True)
        validator.drain(val)
        lifted = ex.execute("select belief from api.claims where id = %s", (c,)).fetchone()[0]
        check(lifted is not None and lifted > PREMISE_CAP, f"and the belief model lifts the cap ({lifted})")
        cs("tms:retract-p-again", [{"op": "set_status", "claim": p, "status": "deprecated", "expect_status": "normal",
                                    "reason": "retracted"}])
        follow(tm, tms.step, once=True)
        check(validator.drain(val) == 1 and latest(c) == "inconclusive" and latest(d) == "inconclusive",
              "withdrawn a second time: flagged again (a new change set, not the first one returned)")

        # Superseded: q replaced by a new claim with the same subject and predicate; what was built on the old q falls.
        cs("tms:supersede-q", [{**fact("urn:x:q", "other premise, corrected", "urn:test:q2"), "ref": "c0"},
                               {"op": "set_status", "claim": q, "status": "deprecated", "expect_status": "normal",
                                "reason": "superseded", "replaced_by": "c0"}])
        follow(tm, tms.step, once=True)
        validator.drain(val)
        check(latest(e) == "inconclusive", "a premise superseded by a new claim undermines what was inferred from the old one")

        # Superseded by the same value: still a withdrawal (D-89 kept, R5-31); the dependant is re-derived, not
        # judged by comparing values.
        cs("tms:r", [fact("urn:x:r", "same", "urn:test:r")])
        r = claim_id("urn:x:r")
        cs("tms:f", [inferred("urn:x:f", "from r", [r])])
        f = claim_id("urn:x:f")
        cs("tms:supersede-r", [{**fact("urn:x:r", "same", "urn:test:r2"), "ref": "c0"},
                               {"op": "set_status", "claim": r, "status": "deprecated", "expect_status": "normal",
                                "reason": "superseded", "replaced_by": "c0"}])
        follow(tm, tms.step, once=True)
        validator.drain(val)
        check(latest(f) == "inconclusive", "a premise superseded by the same value still flags what was inferred from it")

        # Redacted: the premise keeps its identity and lineage, and what was built on it is flagged.
        cs("tms:s", [fact("urn:x:s", "to be erased", "urn:test:s")])
        s_ = claim_id("urn:x:s")
        cs("tms:g", [inferred("urn:x:g", "from s", [s_])])
        g = claim_id("urn:x:g")
        with st.cursor() as cur, run(cur, None) as (run_id, _):
            cur.execute("select api.redact('claim', %s, 'test erasure', %s)", (s_, run_id))
        follow(tm, tms.step, once=True)
        validator.drain(val)
        check(latest(g) == "inconclusive", "a premise redacted flags what was inferred from it")

        # Another scope: the verdict goes to the claim's own scope.
        VOCAB = "urn:kk:scope:vocab"
        cs("tms:v", [fact("urn:x:vp", "vocab premise", "urn:test:vp")], VOCAB)
        vp = claim_id("urn:x:vp")
        cs("tms:vi", [inferred("urn:x:vi", "from vp", [vp])], VOCAB)
        vi = claim_id("urn:x:vi")
        cs("tms:retract-vp", [{"op": "set_status", "claim": vp, "status": "deprecated", "expect_status": "normal",
                               "reason": "retracted"}], VOCAB)
        follow(tm, tms.step, once=True)
        validator.drain(val)
        with connect(url=url) as su:
            where = su.execute("""select s.target_scope from kernel.verification v join kernel.change_set s on s.id = v.change_set
                                  where v.method = %s and v.claim_id = %s""", (tms.METHOD, vi)).fetchall()
        check(latest(vi) == "inconclusive" and where == [(VOCAB,)], "a claim in another scope is judged there, in its own scope")
    subprocess.run(["dropdb", "--if-exists", DB], check=True)
    print("truth-maintenance service checks passed")


if __name__ == "__main__":
    main()
