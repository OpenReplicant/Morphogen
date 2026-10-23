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


def choose(actions: dict, prop: str, kind: str = "setting"):
    """The first action of `kind` on the list that answers `prop`, as (iri, spec), or None."""
    return next(((iri, a) for iri, a in sorted(actions.items())
                 if a.get("kind", "setting") == kind and prop in a.get("answers", [])), None)


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


# ---------------------------------------------------------------- G2: build requests and replacements (R5-21)
SUBSTITUTED_BY = "https://w3id.org/knowledge-kernel/tosca#substitutedBy"
CHECKSUM = "http://spdx.org/rdf/terms#checksumValue"        # the candidate's content hash, on the step
BUILD, REPLACE = "urn:kk:action:build-candidate", "urn:kk:action:replace-provider"


def build_request(anomaly: dict, observation: dict, limit: dict, slot: str, agent: str, scope: str) -> dict:
    """A limit anomaly on a provider's own measure -> a build request for its slot (auto lane: it changes
    nothing running). Inferred from the anomaly, the observation and the limit."""
    key = hashlib.sha256(anomaly["iri"].encode()).hexdigest()[:16]
    iri = f"urn:kk:request:{key}"
    prop, lim, seen = (observation.get("qualifiers") or {}).get(PROP), value(limit), value(observation)
    name = anomaly["target"].rsplit(":", 1)[-1]
    text = (f"{name}'s {prop.rsplit(':', 1)[-1]} is {seen:g}, over its limit {lim:g}. Build a provider of the {slot} slot "
            f"that passes the slot's contract and stays within {lim:g} on the slot's benchmark.")
    premises = sorted(set(anomaly["claim_ids"]) | {str(observation["id"]), str(limit["id"])})
    claim = lambda p, o: {"op": "add_claim", "subject": iri, "predicate": p, "object": o, "evidence_type": "inferred",
                          "derived_from": premises}
    return {"idempotency_key": f"request:{iri}", "attributed_to": agent, "target_scope": scope, "lane": "auto",
            "ops": [claim(DCT_TYPE, {"entity": BUILD}), claim(OA + "hasTarget", {"entity": anomaly["target"]}),
                    claim("http://purl.org/dc/terms/subject", {"entity": f"urn:kk:slot:{slot}"}),
                    claim(OA + "bodyValue", {"value": {"@value": text}})]}


def replacement(request: dict, incumbent: dict, candidate: dict, limit: dict) -> dict:
    """{"plan": ...} or {"none": reason}. incumbent and candidate: the sandbox's measurements of each
    ({provider, passed, total, mean, claim_ids}); limit: the documented limit the request answers."""
    lim = value(limit)
    if candidate["total"] == 0 or candidate["passed"] != candidate["total"]:
        return {"none": f"the candidate passed {candidate['passed']} of {candidate['total']} contract cases"}
    if incumbent["passed"] != incumbent["total"]:
        return {"none": "the incumbent does not pass its own contract: fix that first"}
    if candidate["mean"] is None or incumbent["mean"] is None or candidate["mean"] >= incumbent["mean"]:
        return {"none": f"the candidate is not better ({candidate['mean']} against {incumbent['mean']})"}
    if lim is None or candidate["mean"] > lim:
        return {"none": f"the candidate's {candidate['mean']:g} is still over the limit {lim}"}
    key = hashlib.sha256(request["iri"].encode()).hexdigest()[:16]
    plan = f"urn:kk:plan:{key}"
    old, new = incumbent["provider"].rsplit(":", 1)[-1], candidate["provider"].rsplit(":", 1)[-1]
    prop = (limit.get("qualifiers") or {}).get(PROP)
    text = (f"Run {new} instead of {old}: it passed {candidate['passed']}/{candidate['total']} contract cases and took "
            f"{candidate['mean']:g} s a step in the sandbox against {incumbent['mean']:g} s; predicted to stay within {lim:g}.")
    return {"plan": {"iri": plan, "step": f"{plan}:step:1", "action": REPLACE, "risk": "medium", "label": text,
                     "target": incumbent["provider"], "candidate": candidate["provider"], "sha256": candidate.get("sha256"),
                     "property": prop, "limit": lim,
                     "premises": sorted(set(request["claim_ids"]) | set(incumbent["claim_ids"]) | set(candidate["claim_ids"])
                                        | {str(limit["id"])})}}


def replace_change_set(p: dict, agent: str, scope: str, lane: str) -> dict:
    """The replace plan: like a setting plan, with kkt:substitutedBy naming the candidate (qualified by the
    content hash the builder recorded: what was measured is what a person approves), and the prediction
    on the candidate (it reports under its own name once it runs)."""
    def claim(s, pred, o, q=None):
        c = {"op": "add_claim", "subject": s, "predicate": pred, "object": o, "evidence_type": "inferred",
             "derived_from": p["premises"]}
        if q:
            c["qualifiers"] = q
        return c
    ent = lambda iri: {"entity": iri}
    return {"idempotency_key": f"plan:{p['iri']}", "attributed_to": agent, "target_scope": scope, "lane": lane,
            "ops": [claim(p["iri"], RDF_TYPE, ent(PPLAN + "Plan")), claim(p["iri"], LABEL, {"value": {"@value": p["label"]}}),
                    claim(p["iri"], DCT_TYPE, ent(f"urn:kk:risk:{p['risk']}")),
                    claim(p["step"], RDF_TYPE, ent(SOSA + "Actuation")),
                    claim(p["step"], PPLAN + "isStepOfPlan", ent(p["iri"])),
                    claim(p["step"], DCT_TYPE, ent(p["action"])),
                    claim(p["step"], SOSA + "hasFeatureOfInterest", ent(p["target"])),
                    claim(p["step"], SUBSTITUTED_BY, ent(p["candidate"]), {CHECKSUM: p["sha256"]} if p.get("sha256") else None),
                    claim(p["candidate"], MAX, {"value": {"@value": p["limit"], "@type": XSD + "decimal"}},
                          {PROP: p["property"], PART_OF: p["iri"]})]}

