"""Anomaly worker (the Analyse step of MAPE-K, D-53): whenever the change feed carries observations or
documented limits (and every KK_SWEEP_SECONDS) it reads the current observations and limits and submits
one change set per new anomaly (detect.py). Anomalies are analysis, not decisions: they are applied
directly; the plan derived from them goes to review.

  python -m anomaly [--once]

Ported from rebuild 4 modules/anomaly. Changed: it follows the change feed (R5-04) instead of NOTIFY
patterns, and reads observations of any feature of interest, not only compose services (urn:kk:node:*):
Morphogen observes its own providers (urn:kk:provider:*). Each anomaly's idempotency key names it, so
a pass after a restart submits nothing twice and no durable cursor is needed (R5-18).
Changed (this provider): a pass reads only the newest LATEST + HISTORY observations of each series, which
is all detect.py compares, and looks up status for those alone. If one of them is deprecated or not
numeric, it reads every observation, as the rule does.
Env: DATABASE_URL (a login that may SET ROLE to KK_ROLE), KK_ROLE (default kkm_anomaly), KK_SWEEP_SECONDS.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from kk.lib import connect, follow, run, submit

from .detect import HISTORY, LATEST, MAX, PROP, RESULT, anomalies, change_set, value

MODULE = "urn:kk:module:anomaly"
AGENT = "urn:kk:agent:anomaly"
SCOPE = "urn:kk:scope:default"
COLUMNS = "id, subject, qualifiers, object_value, valid_from, valid_to"
# the observations anomalies() can use: observed, timed, numeric, qualified by the property alone
CANDIDATES = """from api.claims c where c.predicate = %s and c.evidence_type = 'observed'
                and c.valid_from is not null and c.object_value ? '@value'
                and c.qualifiers = jsonb_build_object(%s::text, c.qualifiers -> %s::text)"""
# the newest LATEST + HISTORY of each feature of interest, all the rule reads of it; status is looked up
# only for these rows, not for every observation
NEWEST = f"""select {COLUMNS}, (select s.status from api.claims s where s.id = x.id) as status from (
               select c.id, c.subject, c.qualifiers, c.object_value, c.valid_from, c.valid_to,
                      row_number() over (partition by c.subject order by c.valid_from desc, c.id desc) as rn
               {CANDIDATES}) x
             where x.rn <= %s"""
# every non-deprecated candidate, for when the newest ones include a deprecated or non-numeric observation
ALL = f"select {COLUMNS} {CANDIDATES} and c.status <> 'deprecated'"


def rows_of(cur) -> list[dict]:
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def observations(cur) -> list[dict]:
    cur.execute(NEWEST, (RESULT, PROP, PROP, LATEST + HISTORY))
    rows = rows_of(cur)
    if any(r["status"] == "deprecated" or value(r) is None for r in rows):
        cur.execute(ALL, (RESULT, PROP, PROP))
        rows = rows_of(cur)
    return rows


def one_pass(conn) -> dict:
    with conn.cursor() as cur:
        obs = observations(cur)
        cur.execute(f"""select {COLUMNS} from api.claims where predicate = %s and status <> 'deprecated'""", (MAX,))
        limits = rows_of(cur)
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
