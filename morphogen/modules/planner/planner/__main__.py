"""Planner (the Plan step of MAPE-K): whenever the change feed carries anomalies (and every
KK_SWEEP_SECONDS) it plans for each new limit anomaly from the fixed action list (plan.py), with a
prediction and a risk class, and submits the plan in the lane the autonomy policy gives it (the store
forces review for plan steps today). It never acts; the intent actuator carries out approved steps.

  python -m planner [--once]

A target gets one open plan at a time: an anomaly is planned for only if no plan of this planner on the
same target is waiting for review or still without a verdict, and only if its window starts after the target's latest plan
was recorded (anomalies from before a change are what the change answered). Plans are keyed by their
anomaly, so a restart submits nothing twice (R5-18).
Env: DATABASE_URL (a login that may SET ROLE to KK_ROLE), KK_ROLE (default kkm_planner), KK_INTENT_DIR
(the intent directory, default morphogen/intent), KK_INTENT_ENV (default sandbox), KK_SWEEP_SECONDS.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

from kk.lib import connect, follow, run, submit
from morphogen.policy import actions, autonomy, level, route

from .plan import DCT_TYPE, MAX, OA, PPLAN, RESULT, SOSA, change_set, choose, proposal

MODULE = "urn:kk:module:planner"
AGENT = "urn:kk:agent:planner"
SCOPE = "urn:kk:scope:default"
COLUMNS = "id, subject, predicate, object_entity, object_value, qualifiers, valid_from, valid_to, recorded_at"


def rows(cur, q: str, args=()) -> list[dict]:
    cur.execute(q, args)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def setting(intent: Path, env: str, target: str, name: str):
    """The current value of `name` in the target provider's intent file, or None."""
    f = intent / "environments" / env / (target.rsplit(":", 1)[-1] + ".yaml")
    if not target.startswith("urn:kk:provider:") or not f.exists():
        return None
    v = ((yaml.safe_load(f.read_text()) or {}).get("env") or {}).get(name)
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def one_pass(conn, intent: Path, env: str) -> dict:
    acts, policy = actions(intent), autonomy(intent)
    lane = lambda risk: route(policy, level(policy, MODULE), risk)
    report = {}
    with conn.cursor() as cur:
        claims = rows(cur, f"""select {COLUMNS} from api.claims where subject like 'urn:kk:anomaly:%%'
                               and status <> 'deprecated'""")
        anomalies: dict[str, dict] = {}
        for c in claims:
            a = anomalies.setdefault(c["subject"], {"iri": c["subject"], "claim_ids": [], "kind": None,
                                                    "target": None, "valid_from": c["valid_from"]})
            a["claim_ids"].append(str(c["id"]))
            if c["predicate"] == DCT_TYPE:
                a["kind"] = c["object_entity"]
            elif c["predicate"] == OA + "hasTarget":
                a["target"] = c["object_entity"]
        # This planner's plans per target: when recorded, and whether a verdict closed them.
        plans = rows(cur, """select s.object_entity as target, p.object_entity as plan, s.recorded_at
                             from api.claims s join api.claims p on p.subject = s.subject
                             where s.predicate = %s and p.predicate = %s and s.attributed_to = %s
                               and s.status <> 'deprecated' and p.status <> 'deprecated'""",
                     (SOSA + "hasFeatureOfInterest", PPLAN + "isStepOfPlan", AGENT))
        # Plans still on their way (submitted, validated, waiting for a person): the run names the target.
        pending = {r["target"] for r in rows(cur, """select r.info->>'target' as target from api.change_sets c
                    join kernel.run r on r.id = c.generated_by where c.attributed_to = %s
                     and c.status in ('submitted', 'valid', 'awaiting_review', 'approved')""", (AGENT,))}
        closed = {r["object_entity"] for r in rows(cur, """select object_entity from api.claims
                    where predicate = %s and subject like 'urn:kk:verdict:%%' and status <> 'deprecated'""", (OA + "hasTarget",))}
        for a in sorted(anomalies.values(), key=lambda a: (a["valid_from"] is None, a["valid_from"])):
            if not a["target"] or not a["kind"]:
                continue
            mine = [p for p in plans if p["target"] == a["target"]]
            if a["target"] in pending or any(p["plan"] not in closed for p in mine):
                continue
            if mine and a["valid_from"] is not None and a["valid_from"] <= max(p["recorded_at"] for p in mine):
                continue
            premises = rows(cur, f"""select {COLUMNS} from api.claims where id in
                                     (select derived_from from kernel.claim_derivation where claim_id = any(%s::uuid[]))""",
                            (a["claim_ids"],))
            obs = next((c for c in premises if c["predicate"] == RESULT), None)
            lim = next((c for c in premises if c["predicate"] == MAX), None)
            if obs is None or lim is None:
                continue                                 # a z-score anomaly: no limit to plan against
            chosen = choose(acts, (obs["qualifiers"] or {}).get(SOSA + "observedProperty"))
            current = setting(intent, env, a["target"], chosen[1]["setting"]) if chosen else None
            got = proposal(a, obs, lim, current, acts)
            if "none" in got:
                report[a["iri"]] = got
                continue
            p = got["plan"]
            with run(cur, MODULE, {"anomaly": a["iri"], "target": a["target"]}, used=p["premises"]) as (run_id, outputs):
                res = submit(cur, change_set(p, AGENT, SCOPE, lane(p["risk"])), run_id)
                outputs.update(plan=p["iri"], change_set=str(res["id"]))
            report[a["iri"]] = {"plan": p["iri"], "change_set": str(res["id"]), "lane": res["lane"], "label": p["label"]}
            pending.add(a["target"])
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Plan for anomalies over a documented limit.")
    ap.add_argument("--once", action="store_true", help="one pass, print the result and exit")
    a = ap.parse_args(argv)
    intent = Path(os.environ.get("KK_INTENT_DIR", "morphogen/intent")).resolve()
    env = os.environ.get("KK_INTENT_ENV", "sandbox")
    conn = connect(os.environ.get("KK_ROLE", "kkm_planner"))
    step = lambda c: print(json.dumps(one_pass(c, intent, env), default=str), flush=True)
    if a.once:
        step(conn)
        return 0
    follow(conn, step, wake=lambda e: any(p in (e["predicates"] or []) for p in (DCT_TYPE, OA + "hasTarget")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
