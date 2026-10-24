"""Anomaly worker (the Analyse step of MAPE-K, D-53): whenever the change feed carries observations or
documented limits (and every KK_SWEEP_SECONDS) it reads the current observations and limits and submits
one change set per new anomaly (detect.py). Anomalies are analysis, not decisions: they are applied
directly; the plan derived from them goes to review.

  python -m anomaly [--once]

Ported from rebuild 4 modules/anomaly. Changed: it follows the change feed (R5-04) instead of NOTIFY
patterns, and reads observations of any feature of interest, not only compose services (urn:kk:node:*):
Morphogen observes its own providers (urn:kk:provider:*). It keeps a durable cursor (R5-18, T15): each pass
reads the feed after the seq its last succeeded run handled (from its runs on start, then kept in memory)
and judges, for every change set there, the latest 3 windows of each series it adds (an entry that only
scores or verifies older windows adds none), each against the windows before it; a new or changed limit
re-judges its series' latest 3. The run records the seq it reached (`feed_seq`). Down while windows arrive
one change set at a time, it judges each of them on start, not only the latest 3 of all.
Each anomaly's idempotency key names it, so a pass after a crash between submit and finish submits nothing
twice.
Env: DATABASE_URL (a login that may SET ROLE to KK_ROLE), KK_ROLE (default kkm_anomaly), KK_SWEEP_SECONDS.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from kk.lib import connect, feed_since, follow, resume, run, submit

from .detect import HISTORY, LATEST, MAX, PROP, RESULT, anomalies, change_set

MODULE = "urn:kk:module:anomaly"
AGENT = "urn:kk:agent:anomaly"
SCOPE = "urn:kk:scope:default"
COLUMNS = "id, subject, qualifiers, object_value, valid_from, valid_to"
OBSERVED = "predicate = %s and evidence_type = 'observed' and status <> 'deprecated'"


def key(o: dict) -> tuple:
    return o["subject"], json.dumps(o["qualifiers"], sort_keys=True)


def added(cur, entries: list[tuple]) -> list[set[str]]:
    """Per entry, the claims its change set added: an entry that only scored or verified older windows (a
    belief, a verdict) records no window."""
    ids = sorted(set().union(*(t for _, t in entries)))
    cur.execute("select id::text, change_set from kernel.claim where id = any(%s::uuid[])", (ids,))
    made = dict(cur.fetchall())
    return [{i for i in t if cs is not None and made.get(i) == cs} for cs, t in entries]


def series(cur, entries: list[set[str]]) -> tuple[list[dict], set[str]]:
    """The observations to judge: the windows the entries added, every later window of their series and the
    HISTORY windows before the earliest of them; and the ids to judge, each entry's latest LATEST windows
    of each series."""
    ids = sorted(set().union(*entries))
    cur.execute(f"""with new as (select subject, qualifiers, min(valid_from) t from api.claims
                                  where id = any(%s::uuid[]) and {OBSERVED} group by 1, 2)
                    select o.* from new cross join lateral (
                      (select {COLUMNS} from api.claims c where c.{OBSERVED} and c.subject = new.subject
                          and c.qualifiers = new.qualifiers and c.valid_from >= new.t)
                      union all
                      (select {COLUMNS} from api.claims c where c.{OBSERVED} and c.subject = new.subject
                          and c.qualifiers = new.qualifiers and c.valid_from < new.t
                        order by c.valid_from desc limit {HISTORY})) o""",
                (ids, RESULT, RESULT, RESULT))
    cols = [d.name for d in cur.description]
    obs = [dict(zip(cols, r)) for r in cur.fetchall()]
    by_id = {str(o["id"]): o for o in obs}
    check = set()
    for entry in entries:
        per: dict[tuple, list[dict]] = {}
        for i in entry & by_id.keys():
            per.setdefault(key(by_id[i]), []).append(by_id[i])
        for windows in per.values():
            check |= {str(o["id"]) for o in sorted(windows, key=lambda o: o["valid_from"])[-LATEST:]}
    return obs, check


def latest(cur, keys: set[tuple]) -> tuple[list[dict], set[str]]:
    """Series whose latest windows changed without a new window (a new or changed limit, a withdrawn window):
    each one's latest LATEST windows to judge, and the HISTORY before them."""
    obs, check = [], set()
    for subject, qualifiers in sorted(keys):
        cur.execute(f"""select {COLUMNS} from api.claims where {OBSERVED} and subject = %s and qualifiers = %s::jsonb
                        order by valid_from desc limit {LATEST + HISTORY}""", (RESULT, subject, qualifiers))
        cols = [d.name for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        obs += rows
        check |= {str(r["id"]) for r in rows[:LATEST]}
    return obs, check


_cursor: dict[str, int] = {}   # per database: read from its runs on start, then kept here


def one_pass(conn) -> dict:
    db = conn.info.dbname
    with conn.cursor() as cur:
        since = _cursor[db] if db in _cursor else resume(conn, MODULE)
        reached, entries = feed_since(conn, since, {RESULT, MAX})
        new_windows = added(cur, entries) if entries else []
        changed = set().union(*(t for _, t in entries))
        sets = [cs for cs, _ in entries if cs is not None]
        # Limits the entries added or changed, windows they withdrew: not a belief or verdict on either.
        cur.execute("""select c.subject, c.qualifiers, c.predicate from api.claims c where c.id = any(%s::uuid[])
                        and ((c.predicate = %s and c.status = 'deprecated') or (c.predicate = %s and c.status <> 'deprecated'))
                        and (exists (select 1 from kernel.claim_status s where s.claim_id = c.id and s.change_set = any(%s::uuid[]))
                             or exists (select 1 from kernel.claim k where k.id = c.id and k.change_set = any(%s::uuid[])))""",
                    (sorted(changed), RESULT, MAX, sets, sets))
        keys = {(subject, json.dumps({PROP: (q or {}).get(PROP)} if p == MAX else q, sort_keys=True))
                for subject, q, p in cur.fetchall()}
        if not any(new_windows) and not keys:
            _cursor[db] = reached               # no window, limit or withdrawal: no run; a restart reads these again
            return {"anomalies": {}}
        cur.execute(f"""select {COLUMNS} from api.claims where predicate = %s and status <> 'deprecated'""", (MAX,))
        cols = [d.name for d in cur.description]
        limits = [dict(zip(cols, r)) for r in cur.fetchall()]
        obs, check = series(cur, new_windows)
        more, again = latest(cur, keys)
        seen = {str(o["id"]) for o in obs}
        obs += [o for o in more if str(o["id"]) not in seen]
        found = anomalies(obs, limits, check | again)
        cur.execute("select idempotency_key from api.change_sets where idempotency_key = any(%s)",
                    ([f"anomaly:{a['iri']}" for a in found],))
        done = {r[0] for r in cur.fetchall()}
        new = [a for a in found if f"anomaly:{a['iri']}" not in done]
        submitted = {}
        with run(cur, MODULE, {"since": since, "windows": len(check | again)}) as (run_id, outputs):
            for a in new:
                submitted[a["iri"]] = str(submit(cur, change_set(a, AGENT, SCOPE), run_id)["id"])
            outputs.update(anomalies=len(new), feed_seq=reached)
    _cursor[db] = reached
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
