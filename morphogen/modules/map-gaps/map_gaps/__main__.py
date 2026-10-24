"""Map gap worker (R5-29): lists what a system map still lacks (gaps.py), as questions the interviewer asks next.

Whenever the change feed carries a map claim (a service, a connection, a setting, a limit) and every
KK_SWEEP_SECONDS, a pass reads the current map claims, finds the gaps and submits one change set per gap: an
oa:Annotation (dcterms:type urn:kk:gap-kind:<kind>, oa:hasTarget the service or the unknown peer,
oa:bodyValue the question), inferred and derived from the claims that put the target on the map. An unchanged
gap is a no-op; a gap whose premises changed is superseded; a closed gap has its claims retracted, so the list
shrinks as the person answers. The shape is rebuild 4 modules/map-gaps', with the change feed (R5-04) in
place of NOTIFY patterns.

  python3 -m map_gaps [--once]
Env: DATABASE_URL (a login that may SET ROLE to KK_ROLE), KK_ROLE (default kkm_map_gaps), KK_SWEEP_SECONDS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

from kk.changes import prior as prior_claims, supersede
from kk.lib import connect, follow, run, submit

from .gaps import PREDICATES, gaps

MODULE = "urn:kk:module:map-gaps"
AGENT = "urn:kk:agent:map-gaps"
SCOPE = "urn:kk:scope:default"
OA = "http://www.w3.org/ns/oa#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
DCT_TYPE = "http://purl.org/dc/terms/type"
CLAIMS = """select id, subject, predicate, object_entity, object_value, qualifiers from api.claims
            where status <> 'deprecated' and predicate = any(%s)"""


def change_set(g: dict) -> dict:
    def claim(p, o):
        return {"op": "add_claim", "subject": g["iri"], "predicate": p, "object": o, "evidence_type": "inferred",
                "derived_from": g["premises"]}
    ops = [claim(RDF_TYPE, {"entity": OA + "Annotation"}), claim(DCT_TYPE, {"entity": g["kind"]}),
           claim(OA + "hasTarget", {"entity": g["target"]}), claim(OA + "bodyValue", {"value": {"@value": g["text"]}})]
    digest = hashlib.sha256(json.dumps([g["premises"], g["text"]]).encode()).hexdigest()[:16]
    return {"idempotency_key": f"map-gaps:{g['iri']}|{digest}", "attributed_to": AGENT, "target_scope": SCOPE,
            "ops": ops}


def one_pass(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(CLAIMS, (PREDICATES,))
        cols = [d.name for d in cur.description]
        found = gaps([{**dict(zip(cols, r)), "id": str(r[0])} for r in cur.fetchall()])
        open_ = {g["iri"] for g in found}
        closed = [c for c in prior_claims(cur, AGENT, "map-gaps:", "") if c["subject"] not in open_]
        submitted = {}
        with run(cur, MODULE, {"gaps": len(found)}) as (run_id, outputs):
            for g in found:
                cs = change_set(g)
                old = prior_claims(cur, AGENT, f"map-gaps:{g['iri']}|", cs["idempotency_key"])
                if old:   # the premises changed: the new version replaces the old one
                    supersede(cs, old)
                submitted[g["iri"]] = str(submit(cur, cs, run_id)["id"])
            if closed:
                ids = sorted(str(c["id"]) for c in closed)
                submit(cur, {"idempotency_key": "map-gaps-closed:" + hashlib.sha256(" ".join(ids).encode()).hexdigest()[:16],
                             "attributed_to": AGENT, "target_scope": SCOPE,
                             "ops": [{"op": "set_status", "claim": str(c["id"]), "status": "deprecated",
                                      "reason": "retracted", "expect_status": c["status"]} for c in closed]}, run_id)
            outputs.update(gaps=len(found), closed=len({c["subject"] for c in closed}))
    return {"gaps": len(found), "closed": len({c["subject"] for c in closed}), "change_sets": submitted}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="List what system maps lack, as questions.")
    ap.add_argument("--once", action="store_true", help="one pass, print the result and exit")
    a = ap.parse_args(argv)
    conn = connect(os.environ.get("KK_ROLE", "kkm_map_gaps"))
    if a.once:
        print(json.dumps(one_pass(conn)))
        return 0
    follow(conn, lambda c: print(json.dumps(one_pass(c)), flush=True),
           wake=lambda e: bool(set(PREDICATES) & set(e["predicates"] or [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
