"""The lane-policy slot's own runner (set.yaml `runner:`): installs one provider on a record and submits change sets to
see where the store routes them. Prints "ok: <case id>" per passing case. Never imports the provider.

  python3 runner.py <provider directory>
"""
import sys
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from harness import SCHEMA, Record, check, meta  # noqa: E402

C = "urn:kk:contract:lane-policy/"
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


def claim(s, p, obj):
    return {"op": "add_claim", "subject": s, "predicate": p, "object": obj, "evidence_type": "testimony",
            "references": [{"source_uri": f"urn:test:{s}"}]}


def rules(rec: Record) -> dict:
    return {r["key"]: set(r["value"]) for r in rec.rows("select key, value from kernel.setting where key in "
                                                         "('review_predicates', 'review_types')")}


def main(provider: Path) -> int:
    store = (provider / "schema" / "001_kernel.sql").exists()
    rec = Record("kkc_lane", [], schema=provider / "schema" if store else SCHEMA)
    try:
        baseline = rules(rec)          # the record store's defaults, before a lane provider is installed on them
        if not store:
            if not meta(provider).get("migration"):
                print(f"FAIL: {provider} is neither a record store (schema/) nor has a migration")
                return 1
            rec.psql("-f", str(provider / meta(provider)["migration"]))
        ex = rec.agent("kkc_lane_writer", "urn:kk:agent:contract-writer")
        person = rec.agent("kkc_lane_reviewer", "urn:kk:agent:contract-reviewer", kind="person", grants=("kk_agent", "kk_reviewer"))
        ok = True
        plain = rec.submit(ex, [claim("urn:x:a", LABEL, {"value": {"@value": "a"}})], lane="auto")
        ok &= check(plain["status"] == "applied", C + "ordinary-auto", str(plain))
        typing = rec.submit(ex, [claim("urn:x:newProperty", TYPE, {"entity": "http://www.w3.org/2002/07/owl#ObjectProperty"})], lane="auto")
        ok &= check(typing["status"] == "awaiting_review", C + "typing-reviewed", str(typing))
        sub = rec.submit(ex, [claim("urn:x:p2", "http://www.w3.org/2000/01/rdf-schema#subPropertyOf", {"entity": LABEL})], lane="auto")
        match = rec.submit(ex, [claim("urn:x:t2", "http://www.w3.org/2004/02/skos/core#exactMatch", {"entity": "urn:x:t3"})], lane="auto")
        ok &= check(sub["status"] == match["status"] == "awaiting_review", C + "mapping-reviewed", f"{sub} {match}")
        asked = rec.submit(ex, [claim("urn:x:b", LABEL, {"value": {"@value": "b"}})], lane="review")
        ok &= check(asked["status"] == "awaiting_review", C + "review-kept", str(asked))

        own = rec.submit(person, [claim("urn:x:c", LABEL, {"value": {"@value": "c"}})], lane="review")
        refused = False
        with rec.connect(person) as conn:
            try:
                conn.execute("select api.review(%s, true, 'mine')", (own["id"],))
            except psycopg.Error:
                refused = True
            waiting = rec.rows("select status from kernel.change_set where id = %s", (asked["id"],))[0]["status"]
            conn.execute("select api.review(%s, true, 'fine')", (asked["id"],))
        after = rec.rows("select status from kernel.change_set where id = %s", (asked["id"],))[0]["status"]
        ok &= check(waiting == "awaiting_review" and after == "applied" and refused
                    and rec.rows("select status from kernel.change_set where id = %s", (own["id"],))[0]["status"] == "awaiting_review",
                    C + "waits-for-person", f"waiting {waiting}, after approval {after}, own approval refused {refused}")
        # A change to a mapping's status is a person's decision too (R5-51): once a person approved it, retracting it
        # goes to review, and so does bringing it back; an ordinary claim's retraction stays in the auto lane.
        with rec.connect(person) as conn:
            conn.execute("select api.review(%s, true, 'fine')", (match["id"],))
        mapped = rec.claim("urn:x:t2", "http://www.w3.org/2004/02/skos/core#exactMatch")
        plain_id = rec.claim("urn:x:a")
        def status(cid, to, expect, reason=None):
            return rec.submit(ex, [{"op": "set_status", "claim": cid, "status": to, "expect_status": expect,
                                    **({"reason": reason} if reason else {})}], lane="auto")
        drop = status(mapped, "deprecated", "normal", "retracted")
        drop_plain = status(plain_id, "deprecated", "normal", "retracted")
        with rec.connect(person) as conn:
            conn.execute("select api.review(%s, true, 'fine')", (drop["id"],))
        back = status(mapped, "normal", "deprecated")
        braces = status("{" + mapped + "}", "normal", "deprecated")       # other spellings of the same id
        bare = status(mapped.replace("-", "").upper(), "preferred", "deprecated")
        ok &= check(drop["status"] == back["status"] == braces["status"] == bare["status"] == "awaiting_review"
                    and drop_plain["status"] == "applied", C + "status-reviewed", f"{drop} {back} {braces} {bare} {drop_plain}")
        now = rules(rec)
        ok &= check(baseline and all(baseline[k] <= now.get(k, set()) for k in baseline), C + "only-adds",
                    str({k: sorted(baseline[k] - now.get(k, set())) for k in baseline}))
        return 0 if ok else 1
    finally:
        rec.drop()


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()))
