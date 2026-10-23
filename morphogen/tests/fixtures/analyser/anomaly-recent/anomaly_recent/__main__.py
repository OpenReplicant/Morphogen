"""Anomaly worker, latest windows only (a candidate for the analyser slot): the incumbent's rules
(detect.py, unchanged), but each pass reads only the windows it compares: per feature of interest and
property, the latest 23 (3 judged, up to 20 before them; a deprecated one among them is dropped, not
replaced). The incumbent reads the 5,000 newest
observations of all series, so its pass grows with the record and, past 5,000, cuts older series short.

Otherwise as the incumbent: whenever the change feed carries observations or
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

from kk.lib import connect, follow, run, submit

from .detect import HISTORY, LATEST, MAX, RESULT, anomalies, change_set

MODULE = "urn:kk:module:anomaly-recent"
AGENT = "urn:kk:agent:anomaly"
SCOPE = "urn:kk:scope:default"
COLUMNS = "id, subject, qualifiers, object_value, valid_from, valid_to"


def one_pass(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(f"""select {COLUMNS} from (
                          select c.*, row_number() over (partition by c.subject, c.qualifiers
                                                         order by c.valid_from desc) as rn
                          from kernel.claim c where c.predicate = %s and c.evidence_type = 'observed') x
                        where rn <= %s and kernel.current_status(id) <> 'deprecated'""", (RESULT, LATEST + HISTORY))
        cols = [d.name for d in cur.description]
        obs = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.execute(f"""select {COLUMNS} from api.claims where predicate = %s and status <> 'deprecated'""", (MAX,))
        limits = [dict(zip(cols, r)) for r in cur.fetchall()]
        found = anomalies(obs, limits)
        if not found:
            return {"anomalies": {}}
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
    return {"anomalies": submitted}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Claim anomalies in observations.")
    ap.add_argument("--once", action="store_true", help="one pass, print the result and exit")
    a = ap.parse_args(argv)
    conn = connect(os.environ.get("KK_ROLE", "kkm_anomaly"))
    if a.once:
        print(json.dumps(one_pass(conn)))
        return 0
    follow(conn, lambda c: print(json.dumps(one_pass(c)), flush=True),
           wake=lambda e: bool({RESULT, MAX} & set(e["predicates"] or [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
