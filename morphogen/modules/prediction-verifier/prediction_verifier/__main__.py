"""Prediction verifier (the Verify step): whenever the change feed moves (and every KK_SWEEP_SECONDS) it
checks each open prediction against the observations recorded after its plan was carried out and
records a verdict (verify.py). It is never the agent that made the prediction (invariant 5): a
prediction attributed to this agent is skipped. Verdicts are keyed by their prediction, so a restart
records nothing twice (R5-18).

  python -m prediction_verifier [--once]

Env: DATABASE_URL (a login that may SET ROLE to KK_ROLE), KK_ROLE (default kkm_prediction_verifier),
KK_PREDICTION_WINDOWS (default 3), KK_SETTLE_WINDOWS (default 1), KK_SWEEP_SECONDS.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from kk.lib import connect, follow, run, submit

from .verify import MAX, PART_OF, RESULT, change_set, verdict

MODULE = "urn:kk:module:prediction-verifier"
AGENT = "urn:kk:agent:prediction-verifier"
SCOPE = "urn:kk:scope:default"
STEP_OF = "http://purl.org/net/p-plan#isStepOfPlan"
COLUMNS = "id, subject, qualifiers, object_value, valid_from, valid_to, attributed_to"


def rows(cur, q: str, args=()) -> list[dict]:
    cur.execute(q, args)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def one_pass(conn, windows: int, settle: int) -> dict:
    report = {}
    with conn.cursor() as cur:
        predictions = rows(cur, f"""select {COLUMNS} from api.claims where predicate = %s and qualifiers ? %s
                                    and status <> 'deprecated' and attributed_to <> %s""", (MAX, PART_OF, AGENT))
        if not predictions:
            return report
        done = {r["idempotency_key"] for r in rows(cur, """select idempotency_key from api.change_sets
                 where attributed_to = %s and idempotency_key = any(%s)""",
                 (AGENT, [f"verdict:{p['id']}" for p in predictions]))}
        for p in predictions:
            if f"verdict:{p['id']}" in done:
                continue
            plan = p["qualifiers"][PART_OF]
            steps = [r["subject"] for r in rows(cur, """select subject from api.claims where predicate = %s
                      and object_entity = %s and status <> 'deprecated'""", (STEP_OF, plan))]
            runs = rows(cur, """select status, ended_at, coalesce(cost->>'refused', cost->>'error') as reason
                                from kernel.run where plan_step = any(%s) and agent <> %s and agent <> %s""",
                        (steps, AGENT, p["attributed_to"]))
            obs = rows(cur, f"""select {COLUMNS} from api.claims where predicate = %s and subject = %s
                                and evidence_type = 'observed' and status <> 'deprecated'""", (RESULT, p["subject"]))
            v = verdict(p, runs, obs, windows, settle)
            if "wait" in v:
                report[str(p["id"])] = v
                continue
            with run(cur, MODULE, {"prediction": str(p["id"]), "plan": plan}, used=v["premises"]) as (run_id, outputs):
                res = submit(cur, change_set(p, plan, v, AGENT, SCOPE), run_id)
                outputs.update(verdict=v["verdict"], change_set=str(res["id"]))
            report[str(p["id"])] = {"verdict": v["verdict"], "plan": plan, "text": v["text"], "change_set": str(res["id"])}
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check plans' predictions against what was observed after them.")
    ap.add_argument("--once", action="store_true", help="one pass, print the result and exit")
    a = ap.parse_args(argv)
    windows = int(os.environ.get("KK_PREDICTION_WINDOWS", "3"))
    settle = int(os.environ.get("KK_SETTLE_WINDOWS", "1"))
    conn = connect(os.environ.get("KK_ROLE", "kkm_prediction_verifier"))
    step = lambda c: print(json.dumps(one_pass(c, windows, settle), default=str), flush=True)
    if a.once:
        step(conn)
        return 0
    follow(conn, step, wake=lambda e: RESULT in (e["predicates"] or []))
    return 0


if __name__ == "__main__":
    sys.exit(main())
