"""A limit anomaly -> one plan with a prediction (the Plan step of MAPE-K). Pure functions; no database.

Input: an anomaly over a documented limit (anomaly module: dcterms:type urn:kk:anomaly-kind:limit,
derived from the observation and the limit), the current value of the setting the action changes (from
the provider's intent file, or the compose file of a managed system's service), and the fixed action list
(intent/policies/actions.yaml). An action applies to providers (default) or to a system's nodes
(`applies_to: node`); for a node the step may change another node than the one observed (the one whose
setting answers it, found on the map: R5-25), and the prediction stays on the observed one. An action's
`effect` says how the new value is chosen: `halve` (a feed consumer's poll interval: it lags half of it)
or `proportional` (the property scales with the setting: current x limit / seen / 2, so the prediction
has a margin of two); `integer: true` rounds it down.

The plan (rebuild 4 skill-adaptation-planning's shape, plus a prediction and a risk class):

  <plan>             rdf:type p-plan:Plan; rdfs:label "..."; dcterms:type <risk class>
  <plan>:step:1      rdf:type sosa:Actuation; p-plan:isStepOfPlan <plan>; dcterms:type <action>;
                     sosa:hasFeatureOfInterest <target>; sosa:hasSimpleResult <new value>
  <observed>         bbo:maxValue <limit>  {sosa:observedProperty: <property>, dcterms:isPartOf: <plan>}
                     -- the prediction: after the step, the property of the observed target (the
                     anomaly's) stays within the limit

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


def choose(actions: dict, prop: str, kind: str = "setting", on: str = "provider"):
    """The first action of `kind` on the list that answers `prop` for a provider or a node, as (iri, spec), or None."""
    return next(((iri, a) for iri, a in sorted(actions.items())
                 if a.get("kind", "setting") == kind and a.get("applies_to", "provider") == on
                 and prop in a.get("answers", [])), None)


def applies_to(target: str) -> str:
    return "node" if str(target).startswith("urn:kk:node:") else "provider"


def proposal(anomaly: dict, observation: dict, limit: dict, current, actions: dict, target: str | None = None,
             via: list[str] = ()) -> dict:
    """{"plan": ...} or {"none": reason}. anomaly: {iri, kind, target, claim_ids}; observation and limit:
    claims (id, subject, qualifiers, object_value); current: the setting's value now, or None; target: the
    node the step changes when it is not the anomaly's (found on the map), via: the map's claims that
    lead there (they join the premises)."""
    if anomaly["kind"] != LIMIT_KIND:
        return {"none": "only anomalies over a documented limit are planned for"}
    prop = (observation.get("qualifiers") or {}).get(PROP)
    lim, seen = value(limit), value(observation)
    if prop is None or lim is None or seen is None:
        return {"none": "the anomaly's observation or limit has no value"}
    chosen = choose(actions, prop, on=applies_to(anomaly["target"]))
    if chosen is None:
        return {"none": f"no action on the list answers {prop}"}
    iri, a = chosen
    step_target = target or anomaly["target"]
    if current is None:
        return {"none": f"{step_target} has no intent file setting {a['setting']}: nothing to change"}
    if a.get("effect", "halve") == "proportional":
        new = max(a["min"], min(a["max"], current * lim / seen / 2))
    else:
        # A consumer that reads the feed every p seconds lags p/2 on average: halve the interval, and never
        # leave it above the limit itself.
        new = max(a["min"], min(a["max"], current / 2, lim))
    new = int(new) if a.get("integer") else round(new, 3)
    if new >= current:
        return {"none": f"{a['setting']} is already {current:g}, at the action's minimum {a['min']:g}"}
    key = hashlib.sha256(anomaly["iri"].encode()).hexdigest()[:16]
    plan = f"urn:kk:plan:{key}"
    name, seen_on = step_target.rsplit(":", 1)[-1], anomaly["target"].rsplit(":", 1)[-1]
    whose = "" if step_target == anomaly["target"] else f"{seen_on}'s "
    text = (f"Set {name} {a['setting']} from {current:g} to {new:g}: {whose}{prop.rsplit(':', 1)[-1]} {seen:g} is over "
            f"its limit {lim:g}; predicted to stay within it after the change.")
    return {"plan": {"iri": plan, "step": f"{plan}:step:1", "action": iri, "setting": a["setting"], "risk": a["risk"],
                     "target": step_target, "observed": anomaly["target"], "property": prop, "limit": lim,
                     "from": current, "to": new, "label": text,
                     "premises": sorted(set(anomaly["claim_ids"]) | {str(observation["id"]), str(limit["id"])} | set(via))}}


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
                    claim(p.get("observed", p["target"]), MAX, lit(p["limit"], XSD + "decimal"),
                          {PROP: p["property"], PART_OF: p["iri"]})]}


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


def replacement(request: dict, incumbent: dict, candidate: dict, limit: dict, observed: dict | None = None) -> dict:
    """{"plan": ...} or {"none": reason}. incumbent and candidate: the sandbox's measurements of each
    ({provider, passed, total, mean, claim_ids}); limit: the documented limit the request answers; observed: the
    incumbent's latest observation of it. The candidate's step time is predicted as the observed one scaled by the
    candidate's share of the incumbent's time in the sandbox (T15): the sandbox's workload is not production's,
    so its seconds are compared with each other, not with the limit. Without an observation, the candidate's
    own sandbox time is the prediction."""
    lim = value(limit)
    if candidate["total"] == 0 or candidate["passed"] != candidate["total"]:
        return {"none": f"the candidate passed {candidate['passed']} of {candidate['total']} contract cases"}
    if incumbent["passed"] != incumbent["total"]:
        return {"none": "the incumbent does not pass its own contract: fix that first"}
    if candidate["mean"] is None or incumbent["mean"] is None or candidate["mean"] >= incumbent["mean"]:
        return {"none": f"the candidate is not better ({candidate['mean']} against {incumbent['mean']})"}
    seen = value(observed) if observed else None
    predicted = seen * candidate["mean"] / incumbent["mean"] if seen is not None else candidate["mean"]
    if lim is None or predicted > lim:
        return {"none": f"the candidate's predicted {predicted:g} is still over the limit {lim}"}
    key = hashlib.sha256(request["iri"].encode()).hexdigest()[:16]
    plan = f"urn:kk:plan:{key}"
    old, new = incumbent["provider"].rsplit(":", 1)[-1], candidate["provider"].rsplit(":", 1)[-1]
    prop = (limit.get("qualifiers") or {}).get(PROP)
    text = (f"Run {new} instead of {old}: it passed {candidate['passed']}/{candidate['total']} contract cases and took "
            f"{candidate['mean']:g} s a step in the sandbox against {incumbent['mean']:g} s"
            + (f", so about {predicted:g} s against the {seen:g} s observed" if seen is not None else "")
            + f"; predicted to stay within {lim:g}.")
    return {"plan": {"iri": plan, "step": f"{plan}:step:1", "action": REPLACE, "risk": "medium", "label": text,
                     "target": incumbent["provider"], "candidate": candidate["provider"], "sha256": candidate.get("sha256"),
                     "property": prop, "limit": lim,
                     "premises": sorted(set(request["claim_ids"]) | set(incumbent["claim_ids"]) | set(candidate["claim_ids"])
                                        | {str(limit["id"])} | ({str(observed["id"])} if observed else set()))}}


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

