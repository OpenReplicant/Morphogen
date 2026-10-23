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
