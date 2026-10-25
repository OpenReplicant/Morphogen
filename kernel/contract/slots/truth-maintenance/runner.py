"""The truth-maintenance slot's own runner (set.yaml `runner:`): changes premises step by step in a record, runs one
provider's service once after each step as its own role, and judges the verdicts it recorded. Prints "ok: <case id>"
per passing case. Never imports the provider.

  python3 runner.py <provider directory>
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from harness import Record, check  # noqa: E402

LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
C = "urn:kk:contract:truth-maintenance/"


def fact(s, v, ref=None):
    return {"op": "add_claim", "subject": s, "predicate": LABEL, "object": {"value": {"@value": v}},
            "evidence_type": "testimony", "references": [{"source_uri": ref or f"urn:test:{s}"}]}


def inferred(s, premises):
    return {"op": "add_claim", "subject": s, "predicate": LABEL, "object": {"value": {"@value": f"from {premises}"}},
            "evidence_type": "inferred", "derived_from": premises}


def withdraw(claim, reason="retracted", **more):
    return {"op": "set_status", "claim": claim, "status": "deprecated", "expect_status": "normal", "reason": reason, **more}


def main(provider: Path) -> int:
    rec = Record("kkc_tms", [provider])
    try:
        other = rec.scope("urn:kk:scope:contract-other")
        ex = rec.agent("kkc_tms_extractor", "urn:kk:agent:contract-extractor")
        me = rec.agent_of(provider)
        ids = {}

        def add(scope, *ops):
            rec.submit(ex, list(ops), scope=scope)
            for op in ops:
                if op["op"] == "add_claim":
                    ids[op["subject"].removeprefix("urn:x:")] = rec.claim(op["subject"])

        def run_once() -> list[dict]:
            """The verdicts this pass recorded."""
            since = rec.now()
            rec.service_once(provider)
            return rec.rows("""select v.claim_id::text, v.verdict, v.details, c.scope, cs.target_scope
                               from kernel.verification v join kernel.change_set cs on cs.id = v.change_set
                               join kernel.claim c on c.id = v.claim_id
                               where cs.attributed_to = %s and v.recorded_at > %s::timestamptz""", (me, since))

        def of(verdicts, name):
            return [(v["verdict"], sorted(v["details"].get("withdrawn") or [])) for v in verdicts if v["claim_id"] == ids[name]]

        add("urn:kk:scope:default", fact("urn:x:p", "premise"), fact("urn:x:q", "other premise"))
        add("urn:kk:scope:default", inferred("urn:x:c", [ids["p"]]), inferred("urn:x:e", [ids["q"]]))
        add("urn:kk:scope:default", inferred("urn:x:d", [ids["c"]]))
        add(other, fact("urn:x:s", "premise elsewhere"))
        add(other, inferred("urn:x:t", [ids["s"]]))
        every: list[dict] = []
        ok = True

        got = run_once()
        every += got
        ok &= check(not got, C + "nothing-withdrawn", str(got))

        rec.submit(ex, [withdraw(ids["p"])])
        rec.submit(ex, [withdraw(ids["s"])], scope=other)
        got = run_once()
        every += got
        ok &= check(of(got, "c") == [("inconclusive", [ids["p"]])], C + "retracted", str(of(got, "c")))
        ok &= check(of(got, "d") == [("inconclusive", [ids["p"]])], C + "chain", str(of(got, "d")))
        ok &= check(not of(got, "e"), C + "unrelated", str(of(got, "e")))
        ok &= check(of(got, "t") == [("inconclusive", [ids["s"]])] and all(v["scope"] == v["target_scope"] for v in got),
                    C + "own-scope", str([(v["claim_id"], v["scope"], v["target_scope"]) for v in got]))
        again = run_once()
        ok &= check(not again, C + "once", str(again))

        rec.submit(ex, [{"op": "set_status", "claim": ids["p"], "status": "normal", "expect_status": "deprecated"}])
        got = run_once()
        every += got
        ok &= check(of(got, "c") == [("supported", [])] and of(got, "d") == [("supported", [])], C + "restored",
                    f"c {of(got, 'c')} d {of(got, 'd')}")

        rec.submit(ex, [withdraw(ids["p"])])
        got = run_once()
        every += got
        ok &= check(of(got, "c") == [("inconclusive", [ids["p"]])] and of(got, "d") == [("inconclusive", [ids["p"]])],
                    C + "flagged-again", f"c {of(got, 'c')} d {of(got, 'd')}")

        add("urn:kk:scope:default", fact("urn:x:r", "same"))
        add("urn:kk:scope:default", inferred("urn:x:f", [ids["r"]]))
        rec.submit(ex, [{**fact("urn:x:r", "same", "urn:test:r2"), "ref": "n0"}, withdraw(ids["r"], "superseded", replaced_by="n0")])
        got = run_once()
        every += got
        ok &= check(of(got, "f") == [("inconclusive", [ids["r"]])], C + "superseded-same-value", str(of(got, "f")))

        add("urn:kk:scope:default", fact("urn:x:w", "to be erased"))
        add("urn:kk:scope:default", inferred("urn:x:x", [ids["w"]]))
        rec.redact(ids["w"])
        got = run_once()
        every += got
        ok &= check(of(got, "x") == [("inconclusive", [ids["w"]])], C + "redacted", str(of(got, "x")))

        sets = rec.rows("select status, ops from kernel.change_set where attributed_to = %s", (me,))
        ok &= check(every and all(op.get("op") == "add_verification" for cs in sets for op in cs["ops"])
                    and all(cs["status"] == "applied" for cs in sets), C + "verdicts-only",
                    str([(cs["status"], [op.get("op") for op in cs["ops"]]) for cs in sets]))
        return 0 if ok else 1
    finally:
        rec.drop()


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()))
