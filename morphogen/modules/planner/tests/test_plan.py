"""Planner unit checks: a limit anomaly becomes one plan from the fixed action list, with a prediction and
a risk class; anything it cannot answer is said, not planned. No database.

  python3 tests/test_plan.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "morphogen" / "src")]
from morphogen.policy import actions  # noqa: E402
from planner.plan import MAX, PART_OF, PROP, RESULT, SOSA, change_set, proposal  # noqa: E402

ACTS = actions(ROOT / "morphogen" / "intent")
LAG = "urn:kk:property:feed-lag-seconds-mean"
TARGET = "urn:kk:provider:belief-corroboration"


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg)


anomaly = {"iri": "urn:kk:anomaly:abc", "kind": "urn:kk:anomaly-kind:limit", "target": TARGET, "claim_ids": ["a1", "a2"]}
obs = {"id": "o1", "subject": TARGET, "qualifiers": {PROP: LAG}, "object_value": {"@value": 2.1}}
lim = {"id": "L", "subject": TARGET, "qualifiers": {PROP: LAG}, "object_value": {"@value": 1.0}}

got = proposal(anomaly, obs, lim, 4.0, ACTS)
p = got.get("plan")
check(p is not None and p["action"] == "urn:kk:action:set-poll-seconds" and p["setting"] == "KK_POLL_SECONDS",
      "a feed-lag anomaly is answered by the poll interval")
check(p["from"] == 4.0 and p["to"] == 1.0, "halved, and never above the limit (4 -> min(2, 1))")
check(proposal(anomaly, obs, lim, 1.0, ACTS)["plan"]["to"] == 0.5, "already under the limit: halved (1 -> 0.5)")
check(p["risk"] == "low" and p["premises"] == ["L", "a1", "a2", "o1"], "risk from the action list; premises are the anomaly, observation and limit")
check("none" in proposal(anomaly, obs, lim, 0.1, ACTS), "at the action's minimum: no plan")
check("none" in proposal(anomaly, obs, lim, None, ACTS), "no intent file for the target: no plan")
check("none" in proposal({**anomaly, "kind": "urn:kk:anomaly-kind:zscore"}, obs, lim, 4.0, ACTS), "z-score anomalies are not planned for")
check("none" in proposal(anomaly, {**obs, "qualifiers": {PROP: "urn:kk:property:request-rate"}}, lim, 4.0, ACTS),
      "no action answers the property: no plan")

cs = change_set(p, "urn:kk:agent:planner", "urn:kk:scope:default", "review")
ops = cs["ops"]
check(cs["lane"] == "review" and cs["idempotency_key"] == f"plan:{p['iri']}", "keyed by the plan; the lane it was given")
check(all(o["evidence_type"] == "inferred" and o["derived_from"] == p["premises"] for o in ops), "every claim inferred from the premises")
step = [o for o in ops if o["subject"] == p["step"]]
check({o["predicate"] for o in step} >= {SOSA + "hasFeatureOfInterest", RESULT}
      and next(o for o in step if o["predicate"] == RESULT)["object"]["value"]["@value"] == 1.0, "the step names its target and new value")
pred = next(o for o in ops if o["predicate"] == MAX)
check(pred["subject"] == TARGET and pred["qualifiers"] == {PROP: LAG, PART_OF: p["iri"]}
      and pred["object"]["value"]["@value"] == 1.0, "the prediction: the property within the limit, part of the plan")

# G2: a build request, then a replacement only for a measured candidate that does better (R5-21).
from planner.plan import BUILD, REPLACE, SUBSTITUTED_BY, build_request, replace_change_set, replacement  # noqa: E402

STEP = "urn:kk:property:step-seconds-mean"
an = {"iri": "urn:kk:anomaly:s", "kind": "urn:kk:anomaly-kind:limit", "target": "urn:kk:provider:anomaly", "claim_ids": ["a1"]}
sobs = {"id": "o9", "qualifiers": {PROP: STEP}, "object_value": {"@value": 0.21}}
slim = {"id": "L2", "qualifiers": {PROP: STEP}, "object_value": {"@value": 0.15}}
req = build_request(an, sobs, slim, "analyser", "urn:kk:agent:planner", "urn:kk:scope:default")
check(req["lane"] == "auto" and any(o["object"] == {"entity": BUILD} for o in req["ops"])
      and any(o["object"] == {"entity": "urn:kk:slot:analyser"} for o in req["ops"])
      and all(o["derived_from"] == ["L2", "a1", "o9"] for o in req["ops"]),
      "a step-time anomaly on a provider: a build request for its slot, inferred from the anomaly (auto lane)")
r = {"iri": req["ops"][0]["subject"], "claim_ids": ["q1"]}
inc = {"provider": "urn:kk:provider:anomaly", "passed": 11, "total": 11, "mean": 0.2, "claim_ids": ["m1"]}
cand = {"provider": "urn:kk:provider:anomaly-recent", "passed": 11, "total": 11, "mean": 0.1, "claim_ids": ["m2"]}
check("none" in replacement(r, inc, {**cand, "passed": 10}, slim), "a candidate failing a contract case is not proposed")
check("none" in replacement(r, inc, {**cand, "mean": 0.25}, slim), "a candidate no better than the incumbent is not proposed")
check("none" in replacement(r, {**inc, "mean": 0.3}, {**cand, "mean": 0.2}, slim), "a candidate still over the limit is not proposed")
got = replacement(r, inc, cand, slim)["plan"]
check(got["action"] == REPLACE and got["risk"] == "medium" and set(got["premises"]) == {"q1", "m1", "m2", "L2"},
      "a better candidate: a replacement, citing the request, both measurements and the limit")
ops = replace_change_set(got, "urn:kk:agent:planner", "urn:kk:scope:default", "review")["ops"]
check(any(o["predicate"] == SUBSTITUTED_BY and o["object"] == {"entity": cand["provider"]} for o in ops)
      and any(o["predicate"] == MAX and o["subject"] == cand["provider"] and o["qualifiers"][PROP] == STEP
              and o["object"]["value"]["@value"] == 0.15 for o in ops),
      "the step names the candidate; the prediction: the candidate's step time within the limit")
