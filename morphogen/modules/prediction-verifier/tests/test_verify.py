"""Prediction verifier unit checks: a verdict only from windows wholly after the change, holds or fails
against the predicted limit, untested when the step was never carried out. No database.

  python3 tests/test_verify.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prediction_verifier.verify import OA, PART_OF, PROP, change_set, verdict  # noqa: E402

LAG = "urn:kk:property:feed-lag-seconds-mean"
PLAN = "urn:kk:plan:p1"
T0 = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
W = timedelta(seconds=10)


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg)


pred = {"id": "P", "subject": "urn:kk:provider:belief-corroboration", "qualifiers": {PROP: LAG, PART_OF: PLAN},
        "object_value": {"@value": 1.0}}
obs = lambda i, v: {"id": f"o{i}", "qualifiers": {PROP: LAG}, "object_value": {"@value": v},
                    "valid_from": T0 + i * W, "valid_to": T0 + (i + 1) * W}
ran = [{"status": "succeeded", "ended_at": T0 + 3 * W + timedelta(seconds=2)}]     # during window 3
series = [obs(i, 2.0) for i in range(4)] + [obs(4, 1.5), obs(5, 0.2), obs(6, 0.3), obs(7, 0.25)]

check("wait" in verdict(pred, [], series), "not carried out yet: wait")
check("wait" in verdict(pred, ran, series[:7]), "fewer than 3 windows after the settle window: wait")
v = verdict(pred, ran, series)
check(v["verdict"] == "holds" and v["premises"] == ["P", "o5", "o6", "o7"],
      "holds: windows 5-7 (window 4 settles), derived from the prediction and those observations")
check(verdict(pred, ran, series[:7] + [obs(7, 1.4)])["verdict"] == "fails", "one window over the limit: fails")
check(verdict(pred, [{"status": "failed", "ended_at": T0, "reason": "the action is not on the fixed list"}], series)["verdict"] == "untested",
      "the step failed or was refused: untested")
check(verdict(pred, [{"status": "running", "ended_at": None}], series).get("wait"), "a run still going: wait")
other = [{**o, "qualifiers": {PROP: "urn:kk:property:step-seconds-mean"}} for o in series]
check("wait" in verdict(pred, ran, other), "observations of another property do not count")
cs = change_set(pred, PLAN, v, "urn:kk:agent:prediction-verifier", "urn:kk:scope:default")
check(cs["idempotency_key"] == "verdict:P" and "lane" not in cs
      and all(o["evidence_type"] == "inferred" and o["derived_from"] == v["premises"] for o in cs["ops"])
      and any(o["predicate"] == OA + "hasTarget" and o["object"] == {"entity": PLAN} for o in cs["ops"])
      and any(o["object"] == {"entity": "urn:kk:verdict:holds"} for o in cs["ops"]),
      "the verdict: on the plan, inferred from its premises, keyed by the prediction")
