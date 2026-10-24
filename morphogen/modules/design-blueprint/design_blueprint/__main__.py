"""Design blueprint (R5-29): a described system with no gaps left -> a plan to write its compose file, for a
person to approve. A plain command.

  python3 -m design_blueprint propose SYSTEM

Refuses while the gap finder has an open gap on the system (a question not answered yet), while the
description conflicts (morphogen.blueprint), while a claim it would render has a refuted quote, when the system
has a compose file already, or when the intake filter (the kernel's filter-gitleaks) finds a secret in the plan:
a setting's value would otherwise reach the record and the intent repository. Otherwise it
renders the file (morphogen.blueprint.render) and records, in the review lane, a plan whose label is the file's
whole text and whose one step (urn:kk:action:create-system on urn:kk:system:<name>) names the file's sha256,
inferred from every map claim the file was rendered from. The intent actuator writes the file only if the system
as described then still renders to that text.
Env: DATABASE_URL (a login that may SET ROLE to KK_ROLE), KK_ROLE (default kkm_design_blueprint),
KK_INTENT_DIR (default morphogen/intent).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

from kk.lib import connect, run, submit
from morphogen import blueprint

MODULE = "urn:kk:module:design-blueprint"
AGENT = blueprint.PROPOSER
SCOPE = "urn:kk:scope:default"
ACTION = "urn:kk:action:create-system"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
DCT_TYPE = "http://purl.org/dc/terms/type"
PPLAN = "http://purl.org/net/p-plan#"
SOSA = "http://www.w3.org/ns/sosa/"
OA = "http://www.w3.org/ns/oa#"
_spec = importlib.util.spec_from_file_location(
    "filter_gitleaks", Path(__file__).resolve().parents[4] / "kernel" / "providers" / "filter-gitleaks" / "filter_gitleaks" / "__main__.py")
intake = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(intake)
REFUTED = """select c.id from api.claims c join api.verifications v on v.claim_id = c.id
             where c.id = any(%s::uuid[]) and v.verdict = 'refuted'"""
GAPS = """select g.object_entity, b.object_value->>'@value' from api.claims g
          join api.claims b on b.subject = g.subject and b.predicate = %(body)s and b.status <> 'deprecated'
          where g.predicate = %(target)s and g.attributed_to = 'urn:kk:agent:map-gaps' and g.status <> 'deprecated'
            and (g.object_entity like %(nodes)s or g.object_entity = %(system)s)"""


def plan(name: str, text: str, premises: list[str]) -> dict:
    digest = blueprint.sha(text)
    iri = f"urn:kk:plan:create-{name}-{digest[:12]}"
    step = f"{iri}:step:1"

    def claim(s, p, o):
        return {"op": "add_claim", "subject": s, "predicate": p, "object": o, "evidence_type": "inferred",
                "derived_from": premises}
    ent = lambda x: {"entity": x}  # noqa: E731
    return {"idempotency_key": f"design-blueprint:{iri}", "attributed_to": AGENT, "target_scope": SCOPE, "lane": "review",
            "ops": [claim(iri, RDF_TYPE, ent(PPLAN + "Plan")),
                    claim(iri, LABEL, {"value": {"@value": blueprint.label(name, text)}}),
                    claim(iri, DCT_TYPE, ent("urn:kk:risk:medium")),
                    claim(step, RDF_TYPE, ent(SOSA + "Actuation")), claim(step, PPLAN + "isStepOfPlan", ent(iri)),
                    claim(step, DCT_TYPE, ent(ACTION)), claim(step, SOSA + "hasFeatureOfInterest", ent(f"urn:kk:system:{name}")),
                    claim(step, SOSA + "hasSimpleResult", {"value": {"@value": digest}})]}


def propose(conn, name: str, intent: Path) -> dict:
    if not blueprint.NAME.fullmatch(name):
        return {"refused": f"system name {name!r}"}
    if (intent / "systems" / name / "compose.yaml").exists():
        return {"refused": f"{name} has a compose file already: change it through its settings"}
    with conn.cursor() as cur:
        cur.execute(GAPS, {"body": OA + "bodyValue", "target": OA + "hasTarget", "nodes": f"urn:kk:node:{name}:%",
                           "system": f"urn:kk:system:{name}"})
        open_ = [q for _, q in cur.fetchall()]
        if open_:
            return {"refused": "questions not answered yet", "gaps": sorted(open_)}
        cur.execute(blueprint.MAP, blueprint.params(name))
        cols = [d.name for d in cur.description]
        claims = [dict(zip(cols, r)) for r in cur.fetchall()]
        if not claims:
            return {"refused": f"nothing is described for {name} yet"}
        try:
            text = blueprint.render(blueprint.described(claims, name), name)
        except blueprint.Conflict as e:
            return {"refused": f"the description conflicts: {e}"}
        ids = sorted({str(c["id"]) for c in claims})
        cur.execute(REFUTED, (ids,))
        refuted = [str(r[0]) for r in cur.fetchall()]
        if refuted:
            return {"refused": "a claim the file would be rendered from has a quote the verifier refuted", "claims": refuted}
        cs = plan(name, text, ids)
        screened = intake.filter(cs)                      # fails closed: raises when gitleaks cannot run
        if screened.action != "pass":
            return {"refused": f"the intake filter found a secret in the file ({screened.reason}): record it elsewhere"}
        with run(cur, MODULE, {"system": name}) as (run_id, outputs):
            res = submit(cur, cs, run_id)
            outputs.update(change_set=str(res["id"]), sha256=blueprint.sha(text))
    return {"change_set": str(res["id"]), "plan": cs["ops"][0]["subject"], "sha256": blueprint.sha(text), "text": text}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Propose a described system's compose file, for a person to approve.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose")
    p.add_argument("system")
    a = ap.parse_args(argv)
    intent = Path(os.environ.get("KK_INTENT_DIR", "morphogen/intent")).resolve()
    with connect(os.environ.get("KK_ROLE", "kkm_design_blueprint")) as conn:
        out = propose(conn, a.system, intent)
    print(json.dumps(out))
    return 1 if "refused" in out else 0


if __name__ == "__main__":
    sys.exit(main())
