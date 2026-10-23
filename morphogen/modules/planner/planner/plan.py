"""A limit anomaly -> one plan with a prediction (the Plan step of MAPE-K). Pure functions; no database.

Input: an anomaly over a documented limit (anomaly module: dcterms:type urn:kk:anomaly-kind:limit,
derived from the observation and the limit), the current value of the setting the action changes (from
the provider's intent file), and the fixed action list (intent/policies/actions.yaml).

The plan (rebuild 4 skill-adaptation-planning's shape, plus a prediction and a risk class):

  <plan>             rdf:type p-plan:Plan; rdfs:label "..."; dcterms:type <risk class>
  <plan>:step:1      rdf:type sosa:Actuation; p-plan:isStepOfPlan <plan>; dcterms:type <action>;
                     sosa:hasFeatureOfInterest <target>; sosa:hasSimpleResult <new value>
  <target>           bbo:maxValue <limit>  {sosa:observedProperty: <property>, dcterms:isPartOf: <plan>}
                     -- the prediction: after the step, the property stays within the limit

Every claim is inferred and derived from the anomaly's claims, the observation and the limit. The
prediction's two qualifiers keep it apart from documented limits (which carry only the property), so the
anomaly module never compares observations with a prediction. Which windows the prediction covers is
the verifier's rule, not the planner's (prediction-verifier: KK_PREDICTION_WINDOWS after the actuation).
"""
from __future__ import annotations

import hashlib

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
DCT_TYPE = "http://purl.org/dc/terms/type"
PART_OF = "http://purl.org/dc/terms/isPartOf"
PPLAN = "http://purl.org/net/p-plan#"
SOSA = "http://www.w3.org/ns/sosa/"
OA = "http://www.w3.org/ns/oa#"
XSD = "http://www.w3.org/2001/XMLSchema#"
MAX = "https://www.irit.fr/recherches/MELODI/ontologies/BBO#maxValue"
RESULT, PROP = SOSA + "hasSimpleResult", SOSA + "observedProperty"
LIMIT_KIND = "urn:kk:anomaly-kind:limit"


def value(c: dict):
    try:
        return float((c.get("object_value") or {}).get("@value"))
    except (TypeError, ValueError):
        return None


def choose(actions: dict, prop: str):
    """The first action on the list that answers `prop`, as (iri, spec), or None."""
    return next(((iri, a) for iri, a in sorted(actions.items()) if prop in a.get("answers", [])), None)


def proposal(anomaly: dict, observation: dict, limit: dict, current, actions: dict) -> dict:
    """{"plan": ...} or {"none": reason}. anomaly: {iri, kind, target, claim_ids}; observation and limit:
    claims (id, subject, qualifiers, object_value); current: the setting's value now, or None."""
    if anomaly["kind"] != LIMIT_KIND:
        return {"none": "only anomalies over a documented limit are planned for"}
    prop = (observation.get("qualifiers") or {}).get(PROP)
    lim, seen = value(limit), value(observation)
    if prop is None or lim is None or seen is None:
        return {"none": "the anomaly's observation or limit has no value"}
    chosen = choose(actions, prop)
    if chosen is None:
        return {"none": f"no action on the list answers {prop}"}
    iri, a = chosen
    if current is None:
        return {"none": f"{anomaly['target']} has no intent file setting {a['setting']}: nothing to change"}
    # A consumer that reads the feed every p seconds lags p/2 on average: halve the interval, and never
    # leave it above the limit itself.
    new = round(max(a["min"], min(a["max"], current / 2, lim)), 3)
    if new >= current:
        return {"none": f"{a['setting']} is already {current:g}, at the action's minimum {a['min']:g}"}
    key = hashlib.sha256(anomaly["iri"].encode()).hexdigest()[:16]
    plan = f"urn:kk:plan:{key}"
    name = anomaly["target"].rsplit(":", 1)[-1]
    text = (f"Set {name} {a['setting']} from {current:g} to {new:g}: {prop.rsplit(':', 1)[-1]} {seen:g} is over "
            f"its limit {lim:g}; predicted to stay within it after the change.")
    return {"plan": {"iri": plan, "step": f"{plan}:step:1", "action": iri, "setting": a["setting"], "risk": a["risk"],
                     "target": anomaly["target"], "property": prop, "limit": lim, "from": current, "to": new,
                     "label": text, "premises": sorted(set(anomaly["claim_ids"]) | {str(observation["id"]), str(limit["id"])})}}


def change_set(p: dict, agent: str, scope: str, lane: str) -> dict:
    def claim(s, pred, o, q=None):
        c = {"op": "add_claim", "subject": s, "predicate": pred, "object": o, "evidence_type": "inferred",
             "derived_from": p["premises"]}
        if q:
            c["qualifiers"] = q
        return c
    ent = lambda iri: {"entity": iri}
    lit = lambda v, t=None: {"value": {"@value": v, **({"@type": t} if t else {})}}
    return {"idempotency_key": f"plan:{p['iri']}", "attributed_to": agent, "target_scope": scope, "lane": lane,
            "ops": [claim(p["iri"], RDF_TYPE, ent(PPLAN + "Plan")), claim(p["iri"], LABEL, lit(p["label"])),
                    claim(p["iri"], DCT_TYPE, ent(f"urn:kk:risk:{p['risk']}")),
                    claim(p["step"], RDF_TYPE, ent(SOSA + "Actuation")),
                    claim(p["step"], PPLAN + "isStepOfPlan", ent(p["iri"])),
                    claim(p["step"], DCT_TYPE, ent(p["action"])),
                    claim(p["step"], SOSA + "hasFeatureOfInterest", ent(p["target"])),
                    claim(p["step"], RESULT, lit(p["to"], XSD + "decimal")),
                    claim(p["target"], MAX, lit(p["limit"], XSD + "decimal"), {PROP: p["property"], PART_OF: p["iri"]})]}
