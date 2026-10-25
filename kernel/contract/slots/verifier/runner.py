"""The verifier slot's own runner (set.yaml `runner:`): seeds a record, runs one provider's service once as its own
role, and judges what it recorded. Prints "ok: <case id>" per passing case. Never imports the provider.

  python3 runner.py <provider directory>
"""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from harness import Record, check, meta  # noqa: E402

LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
C = "urn:kk:contract:verifier/"
SOURCE = "Line one.\nThe pump in hall 3 runs at 40 litres per minute.\nLine three.\n"


def main(provider: Path) -> int:
    applies = set(meta(provider).get("applies_to") or [])
    if not applies:
        print(f"FAIL: {provider}/provider.yaml declares no applies_to (evidence types or predicate IRIs)")
        return 1
    rec = Record("kkc_verifier", [provider])
    try:
        root = Path(tempfile.mkdtemp(prefix="kkc-verifier-"))
        (root / "doc.txt").write_text(SOURCE)
        other = rec.scope("urn:kk:scope:contract-other")
        ex = rec.agent("kkc_verifier_extractor", "urn:kk:agent:contract-extractor")
        role = meta(provider)["role"]
        me = rec.agent_of(provider)

        def claim(s, evidence, quote=None, source="file:doc.txt"):
            ref = {"source_uri": source, **({"quote": quote} if quote else {})}
            return {"op": "add_claim", "subject": s, "predicate": LABEL, "object": {"value": {"@value": s}},
                    "evidence_type": evidence, "references": [ref]}
        rec.submit(ex, [claim("urn:x:found", "extracted", "The pump in hall 3 runs at 40 litres per minute."),
                        claim("urn:x:missing", "extracted", "The pump in hall 3 runs at 90 litres per minute."),
                        claim("urn:x:told", "testimony", source="urn:x:interview"),
                        claim("urn:x:parsed", "deterministic", source="file:doc.txt"),
                        claim("urn:x:gone", "extracted", "Line three.")])
        rec.submit(ex, [claim("urn:x:elsewhere", "extracted", "Line one.")], scope=other)
        rec.submit(role, [claim("urn:x:mine", "extracted", "Line one.")])
        ids = {s.split(":")[-1]: rec.claim(s) for s in
               ("urn:x:found", "urn:x:missing", "urn:x:told", "urn:x:parsed", "urn:x:gone", "urn:x:elsewhere", "urn:x:mine")}
        rec.redact(ids["gone"])
        kinds = {k: rec.rows("select evidence_type, predicate from kernel.claim where id = %s", (v,))[0] for k, v in ids.items()}
        within = {k for k, r in kinds.items() if r["evidence_type"] in applies or r["predicate"] in applies}

        started = rec.now()
        rec.service_once(provider, env={"KK_SOURCE_ROOT": str(root), "KK_ARTIFACTS": str(root / "artifacts")})
        verdicts = rec.rows("""select v.claim_id::text, v.verdict, v.method, c.scope, cs.target_scope
                               from kernel.verification v join kernel.change_set cs on cs.id = v.change_set
                               join kernel.claim c on c.id = v.claim_id where cs.attributed_to = %s""", (me,))
        by = {}
        for v in verdicts:
            by.setdefault(v["claim_id"], []).append(v)
        mine = rec.rows("select status, ops from kernel.change_set where attributed_to = %s and submitted_at > %s::timestamptz",
                        (me, started))
        ok = True
        ok &= check(all(op.get("op") == "add_verification" for cs in mine if cs["status"] == "applied" for op in cs["ops"]),
                    C + "verdicts-only", str([op.get("op") for cs in mine for op in cs["ops"]]))
        expected = sorted(within - {"mine", "gone"})
        got = {k: len(by.get(ids[k], [])) for k in expected}
        ok &= check(expected and all(n == 1 for n in got.values()), C + "applies-to",
                    f"verdicts per claim it declares: {got} (applies_to {sorted(applies)})")
        outside = sorted(set(ids) - within)
        ok &= check(not any(by.get(ids[k]) for k in outside), C + "outside-applies-to",
                    str({k: by.get(ids[k]) for k in outside}))
        ok &= check(not by.get(ids["mine"]) and not any(cs["status"] in ("failed", "invalid", "rejected") for cs in mine),
                    C + "not-its-own", f"own claim: {by.get(ids['mine'])}; refused: {[cs['status'] for cs in mine]}")
        ok &= check(not by.get(ids["gone"]), C + "redacted", str(by.get(ids["gone"])))
        ok &= check(verdicts and all(v["scope"] == v["target_scope"] for v in verdicts)
                    and (ids["elsewhere"] in by or "elsewhere" not in within), C + "own-scope",
                    str([(v["claim_id"], v["scope"], v["target_scope"]) for v in verdicts]))
        ok &= check(verdicts and all(v["verdict"] in ("supported", "refuted", "inconclusive") and v["method"] for v in verdicts),
                    C + "verdict-values", str(verdicts))
        again = rec.now()
        rec.service_once(provider, env={"KK_SOURCE_ROOT": str(root), "KK_ARTIFACTS": str(root / "artifacts")})
        later = rec.rows("select id from kernel.change_set where attributed_to = %s and submitted_at > %s::timestamptz", (me, again))
        ok &= check(not later, C + "once", f"{len(later)} change sets on a second pass")
        return 0 if ok else 1
    finally:
        rec.drop()


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()))
