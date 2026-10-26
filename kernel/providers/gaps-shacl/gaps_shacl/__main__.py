"""The kernel's gap finder as a service (R5-47): what the claims lack, by the warning shapes the installed packs carry
(gaps.py), as questions a person or an interviewer answers next.

Whenever the change feed carries a claim with a predicate the shapes look at (gaps.reads) and every KK_SWEEP_SECONDS,
a pass reads those current claims, finds the gaps and submits one change set per gap: an oa:Annotation
(dcterms:type its kind, oa:hasTarget what it is about, oa:bodyValue the question), inferred and derived from the
claims its shape declares it rests on. An unchanged open gap is a no-op; a gap whose premises or question changed is
superseded; a closed gap has its claims retracted, so the list shrinks as people answer; a gap that opens again is
recorded again, under a key of its own (the key counts the gap's earlier change sets). The bookkeeping is map-gaps'
(Morphogen's first gap finder, its rules in Python).

  python3 -m gaps_shacl [--once]
Env: DATABASE_URL (a login that may SET ROLE to KK_ROLE), KK_ROLE (default kkm_gaps_shacl), KK_SWEEP_SECONDS,
KK_SHAPES_DIR (default: the kernel's packs).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

from kk.changes import prior as prior_claims, supersede
from kk.lib import connect, follow, run, submit

from .gaps import gaps, reads, shapes

MODULE = "urn:kk:module:gaps-shacl"
AGENT = "urn:kk:agent:gaps-shacl"
RULES = shapes()
PREDICATES = reads(RULES)
SCOPE = "urn:kk:scope:default"
OA = "http://www.w3.org/ns/oa#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
DCT_TYPE = "http://purl.org/dc/terms/type"
OPEN = """select c.id, c.subject, c.predicate, c.qualifiers, c.valid_from, c.status, s.idempotency_key
          from api.claims c join api.change_sets s on s.id = c.change_set
          where c.attributed_to = %(agent)s and c.status <> 'deprecated' and starts_with(s.idempotency_key, %(prefix)s)"""
SETS = """select count(*) from api.change_sets where attributed_to = %(agent)s and starts_with(idempotency_key, %(prefix)s)"""
CLAIMS = """select id, subject, predicate, object_entity, object_value, qualifiers from api.claims
            where status <> 'deprecated' and predicate = any(%s)"""


def change_set(g: dict, generation: int = 0) -> dict:
    def claim(p, o):
        return {"op": "add_claim", "subject": g["iri"], "predicate": p, "object": o, "evidence_type": "inferred",
                "derived_from": g["premises"]}
    ops = [claim(RDF_TYPE, {"entity": OA + "Annotation"}), claim(DCT_TYPE, {"entity": g["kind"]}),
           claim(OA + "hasTarget", {"entity": g["target"]}), claim(OA + "bodyValue", {"value": {"@value": g["text"]}})]
    digest = hashlib.sha256(json.dumps([g["premises"], g["text"]]).encode()).hexdigest()[:16]
    return {"idempotency_key": f"gaps:{g['iri']}|{digest}|{generation}", "attributed_to": AGENT, "target_scope": SCOPE,
            "ops": ops}


def digest_of(key: str) -> str:
    return key.split("|")[1] if key.count("|") >= 1 else ""


def one_pass(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(CLAIMS, (PREDICATES,))
        cols = [d.name for d in cur.description]
        found = gaps([{**dict(zip(cols, r)), "id": str(r[0])} for r in cur.fetchall()], RULES)
        open_ = {g["iri"] for g in found}
        closed = [c for c in prior_claims(cur, AGENT, "gaps:", "") if c["subject"] not in open_]
        submitted = {}
        with run(cur, MODULE, {"gaps": len(found)}) as (run_id, outputs):
            for g in found:
                prefix = f"gaps:{g['iri']}|"
                cur.execute(OPEN, {"agent": AGENT, "prefix": prefix})
                cols = [d.name for d in cur.description]
                old = [dict(zip(cols, r)) for r in cur.fetchall()]
                want = digest_of(change_set(g)["idempotency_key"])
                if old and {digest_of(c["idempotency_key"]) for c in old} == {want}:
                    continue                    # open, as it was: nothing to record
                cur.execute(SETS, {"agent": AGENT, "prefix": prefix})
                cs = change_set(g, cur.fetchone()[0])
                if old:   # the premises changed: the new version replaces the old one
                    supersede(cs, old)
                submitted[g["iri"]] = str(submit(cur, cs, run_id)["id"])
            if closed:
                ids = sorted(str(c["id"]) for c in closed)
                submit(cur, {"idempotency_key": "gaps-closed:" + hashlib.sha256(" ".join(ids).encode()).hexdigest()[:16],
                             "attributed_to": AGENT, "target_scope": SCOPE,
                             "ops": [{"op": "set_status", "claim": str(c["id"]), "status": "deprecated",
                                      "reason": "retracted", "expect_status": c["status"]} for c in closed]}, run_id)
            outputs.update(gaps=len(found), closed=len({c["subject"] for c in closed}))
    return {"gaps": len(found), "closed": len({c["subject"] for c in closed}), "change_sets": submitted}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="List what the claims lack, by the packs' shapes, as questions.")
    ap.add_argument("--once", action="store_true", help="one pass, print the result and exit")
    a = ap.parse_args(argv)
    conn = connect(os.environ.get("KK_ROLE", "kkm_gaps_shacl"))
    if a.once:
        print(json.dumps(one_pass(conn)))
        return 0
    follow(conn, lambda c: print(json.dumps(one_pass(c)), flush=True),
           wake=lambda e: bool(set(PREDICATES) & set(e["predicates"] or [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
