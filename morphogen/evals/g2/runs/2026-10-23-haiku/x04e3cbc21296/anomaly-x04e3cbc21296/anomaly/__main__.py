"""Anomaly worker (the Analyse step of MAPE-K, D-53): whenever the change feed carries observations or
documented limits (and every KK_SWEEP_SECONDS) it reads the current observations and limits and submits
one change set per new anomaly (detect.py). Anomalies are analysis, not decisions: they are applied
directly; the plan derived from them goes to review.

  python -m anomaly [--once]

Ported from rebuild 4 modules/anomaly. Changed: it follows the change feed (R5-04) instead of NOTIFY
patterns, and reads observations of any feature of interest, not only compose services (urn:kk:node:*):
Morphogen observes its own providers (urn:kk:provider:*). Each anomaly's idempotency key names it, so
a pass after a restart submits nothing twice and no durable cursor is needed (R5-18).
Env: DATABASE_URL (a login that may SET ROLE to KK_ROLE), KK_ROLE (default kkm_anomaly), KK_SWEEP_SECONDS.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from kk.lib import connect, feed_head, follow, run, submit

from .detect import MAX, RESULT, anomalies, change_set

MODULE = "urn:kk:module:anomaly"
AGENT = "urn:kk:agent:anomaly"
SCOPE = "urn:kk:scope:default"
COLUMNS = "id, subject, qualifiers, object_value, valid_from, valid_to"


def one_pass(conn, seen: dict | None = None) -> dict:
    """One pass. With `seen` (kept by the caller across passes), a pass is skipped while the change feed has
    not moved since the last one: observations and limits change only through applied change sets and
    redactions, which are feed entries, so nothing new can be found. The feed head is read before the claims,
    so a change landing in between is caught by the next pass."""
    head = feed_head(conn)
    if seen is not None and seen.get("head") == head:
        return {"anomalies": {}}
    submitted = scan(conn)
    if seen is not None:
        seen["head"] = head
    return {"anomalies": submitted}


def scan(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(f"""select {COLUMNS} from api.claims where predicate = %s
                        and evidence_type = 'observed' and status <> 'deprecated'
                        order by valid_from desc limit 5000""", (RESULT,))
        cols = [d.name for d in cur.description]
        obs = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.execute(f"""select {COLUMNS} from api.claims where predicate = %s and status <> 'deprecated'""", (MAX,))
        limits = [dict(zip(cols, r)) for r in cur.fetchall()]
        found = anomalies(obs, limits)
        if not found:
            return {}
        cur.execute("select idempotency_key from api.change_sets where idempotency_key = any(%s)",
                    ([f"anomaly:{a['iri']}" for a in found],))
        done = {r[0] for r in cur.fetchall()}
        new = [a for a in found if f"anomaly:{a['iri']}" not in done]
        submitted = {}
        if new:
            with run(cur, MODULE, {"anomalies": len(new)}) as (run_id, outputs):
                for a in new:
                    submitted[a["iri"]] = str(submit(cur, change_set(a, AGENT, SCOPE), run_id)["id"])
                outputs.update(anomalies=len(new))
    return submitted


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Claim anomalies in observations.")
    ap.add_argument("--once", action="store_true", help="one pass, print the result and exit")
    a = ap.parse_args(argv)
    conn = connect(os.environ.get("KK_ROLE", "kkm_anomaly"))
    if a.once:
        print(json.dumps(one_pass(conn)))
        return 0
    seen: dict = {}
    follow(conn, lambda c: print(json.dumps(one_pass(c, seen)), flush=True),
           wake=lambda e: bool({RESULT, MAX} & set(e["predicates"] or [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
