"""A plan's prediction against what was observed after its step was carried out (the Verify step).
Pure functions; no database.

A prediction is the planner's `<target> bbo:maxValue <n> {sosa:observedProperty: <p>, dcterms:isPartOf:
<plan>}`: after the plan, <p> of <target> stays at or below <n>. The plan was carried out when a run with
plan_step one of its steps succeeded (the actuator's run; it never claims the outcome). The verdict uses
the first WINDOWS observations of <p> on <target> that start at least SETTLE windows after that run ended
(the reconciler restarts the service, and the window in progress mixes before and after):

  holds      every one is within the limit
  fails      at least one is over it
  untested   the step's run failed or was refused: nothing changed, so nothing can be learned

  <verdict>  rdf:type oa:Annotation; dcterms:type urn:kk:verdict:<holds|fails|untested>;
             oa:hasTarget <plan>; oa:bodyValue "..."
             inferred, derived from the prediction and the observations compared
"""
from __future__ import annotations

import hashlib

SOSA = "http://www.w3.org/ns/sosa/"
OA = "http://www.w3.org/ns/oa#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
DCT_TYPE = "http://purl.org/dc/terms/type"
PART_OF = "http://purl.org/dc/terms/isPartOf"
MAX = "https://www.irit.fr/recherches/MELODI/ontologies/BBO#maxValue"
RESULT, PROP = SOSA + "hasSimpleResult", SOSA + "observedProperty"
WINDOWS, SETTLE = 3, 1


def value(c: dict):
    try:
        return float((c.get("object_value") or {}).get("@value"))
    except (TypeError, ValueError):
        return None


def verdict(prediction: dict, runs: list[dict], observations: list[dict],
            windows: int = WINDOWS, settle: int = SETTLE) -> dict:
    """{"verdict": kind, "text", "premises"} or {"wait": reason}. runs: the runs that carried out (or
    refused) one of the plan's steps (status, ended_at); observations: claims of the prediction's
    target (subject, qualifiers, object_value, valid_from, valid_to)."""
    q = prediction.get("qualifiers") or {}
    prop, plan, limit = q.get(PROP), q.get(PART_OF), value(prediction)
    if not prop or not plan or limit is None:
        return {"wait": "not a prediction (no property, plan or limit)"}
    done = [r for r in runs if r.get("ended_at") and r.get("status") in ("succeeded", "failed")]
    if not done:
        return {"wait": "the plan has not been carried out yet"}
    ok = sorted((r for r in done if r["status"] == "succeeded"), key=lambda r: r["ended_at"])
    if not ok:
        return {"verdict": "untested", "premises": [str(prediction["id"])],
                "text": f"{plan} was not carried out ({done[0].get('reason') or 'the step failed'}); the prediction was not tested."}
    at = ok[0]["ended_at"]
    series = sorted((o for o in observations
                     if (o.get("qualifiers") or {}) == {PROP: prop} and o.get("valid_from") and o.get("valid_to")
                     and value(o) is not None), key=lambda o: o["valid_from"])
    if not series:
        return {"wait": "no observations yet"}
    width = series[-1]["valid_to"] - series[-1]["valid_from"]
    after = [o for o in series if o["valid_from"] >= at + settle * width][:windows]
    if len(after) < windows:
        return {"wait": f"{len(after)} of {windows} windows observed after the change"}
    values = [value(o) for o in after]
    over = [v for v in values if v > limit]
    name = prop.rsplit(":", 1)[-1]
    text = (f"{name} was {', '.join(f'{v:g}' for v in values)} in the {windows} windows after the change: "
            + (f"within the predicted limit {limit:g}." if not over else f"over the predicted limit {limit:g} in {len(over)}."))
    return {"verdict": "fails" if over else "holds", "text": text,
            "premises": [str(prediction["id"])] + [str(o["id"]) for o in after]}


def change_set(prediction: dict, plan: str, v: dict, agent: str, scope: str) -> dict:
    iri = "urn:kk:verdict:" + hashlib.sha256(str(prediction["id"]).encode()).hexdigest()[:16]

    def claim(p, o):
        return {"op": "add_claim", "subject": iri, "predicate": p, "object": o, "evidence_type": "inferred",
                "derived_from": v["premises"]}
    return {"idempotency_key": f"verdict:{prediction['id']}", "attributed_to": agent, "target_scope": scope,
            "ops": [claim(RDF_TYPE, {"entity": OA + "Annotation"}),
                    claim(DCT_TYPE, {"entity": f"urn:kk:verdict:{v['verdict']}"}),
                    claim(OA + "hasTarget", {"entity": plan}),
                    claim(OA + "bodyValue", {"value": {"@value": v["text"]}})]}

