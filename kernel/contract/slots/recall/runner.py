"""The recall slot's own runner (set.yaml `runner:`): seeds a record, runs one provider's service once as its own role,
and asks `api.recall` as a reader. Prints "ok: <case id>" per passing case. Never imports the provider.

  python3 runner.py <provider directory>
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from harness import Record, check, meta  # noqa: E402

LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
C = "urn:kk:contract:recall/"


def fact(s, v):
    return {"op": "add_claim", "subject": s, "predicate": LABEL, "object": {"value": {"@value": v}},
            "evidence_type": "testimony", "references": [{"source_uri": f"urn:test:{s}"}]}


def main(provider: Path) -> int:
    rec = Record("kkc_recall", [provider])
    try:
        role = meta(provider).get("role")
        ex = rec.agent("kkc_recall_writer", "urn:kk:agent:contract-writer")
        reader = rec.agent("kkc_recall_reader", "urn:kk:agent:contract-reader")
        secret = rec.scope("urn:kk:scope:contract-secret", readers=tuple(r for r in (ex, role) if r))
        rec.submit(ex, [fact("urn:x:pump", "the centrifugal pump in hall three delivers forty litres per minute"),
                        fact("urn:x:valve", "the relief valve opens at six bar"),
                        fact("urn:x:boiler", "the boiler feeds hall two"),
                        fact("urn:x:fan", "an exhaust fan cools the pump room"),
                        fact("urn:x:old", "the obsolete gearbox lubricant schedule"),
                        fact("urn:x:erased", "the zirconium manifold serial")])
        rec.submit(ex, [fact("urn:x:hidden", "centrifugal pump hall three forty litres per minute delivers centrifugal")], scope=secret)
        ids = {s: rec.claim(f"urn:x:{s}") for s in ("pump", "valve", "boiler", "fan", "old", "erased", "hidden")}
        rec.submit(ex, [{"op": "set_status", "claim": ids["old"], "status": "deprecated", "reason": "retracted"}])
        if role:
            rec.service_once(provider)

        def ask(text, limit=20):
            return rec.rows("select api.recall(%s, %s) r", (text, limit), role=reader)[0]["r"] or []
        ok = True
        if ids["erased"] not in {str(r["id"]) for r in ask("zirconium manifold serial")}:
            print("FAIL: a claim is not found by its own words before it is redacted; the redacted case would prove nothing")
            return 1
        rec.redact(ids["erased"])         # after the claim was indexed: the index must drop it
        got = ask("which centrifugal pump delivers forty litres")
        first = str(got[0]["id"]) if got else None
        ok &= check(first == ids["pump"], C + "match-first", str([(r.get("subject"), r.get("rank")) for r in got]))
        ok &= check(got and all("id" in r and "belief" in r and "rank" in r for r in got), C + "cites", str(got[:1]))
        ok &= check(ask("quasar nebula telescope") == [], C + "no-match", str(ask("quasar nebula telescope")))
        ok &= check(len(ask("the hall pump valve boiler fan", 2)) == 2, C + "limit", str(len(ask("the hall pump valve boiler fan", 2))))
        ok &= check(ids["hidden"] not in {str(r["id"]) for r in got + ask("centrifugal", 200)}, C + "clearance",
                    "a claim of a scope the reader cannot read was returned")
        ok &= check(ids["old"] not in {str(r["id"]) for r in ask("obsolete gearbox lubricant schedule")}, C + "deprecated",
                    str(ask("obsolete gearbox lubricant schedule")))
        rec.submit(ex, [fact("urn:x:late", "a peristaltic dosing unit added later")])
        if role:
            rec.service_once(provider)
        ok &= check(ids["erased"] not in {str(r["id"]) for r in ask("zirconium manifold serial")}, C + "redacted",
                    str(ask("zirconium manifold serial")))
        late = rec.claim("urn:x:late")
        ok &= check([str(r["id"]) for r in ask("peristaltic dosing unit")][:1] == [late], C + "follows-feed",
                    str(ask("peristaltic dosing unit")))
        return 0 if ok else 1
    finally:
        rec.drop()


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()))
