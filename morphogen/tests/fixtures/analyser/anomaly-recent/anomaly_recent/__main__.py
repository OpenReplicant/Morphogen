"""Anomaly worker, lean passes (a candidate for the analyser slot): the incumbent's rules (detect.py) and its
reading of the feed (each change set's latest 3 windows of each series it records, judged once; a new limit
or a withdrawn window re-judges its series' latest 3), with fewer round trips per pass:

  the cursor is read from its runs once, on start, then kept in memory;
  a short page of the feed is the last one (the incumbent asks once more and gets nothing);
  what the entries touched, the windows to compare and the limits are read in one query;
  a run is recorded only when it submits anomalies, so a restart replays the entries read since the last
  one (each anomaly's idempotency key keeps the replay from submitting anything twice).

  python -m anomaly_recent [--once]

Env: DATABASE_URL (a login that may SET ROLE to KK_ROLE), KK_ROLE (default kkm_anomaly), KK_SWEEP_SECONDS.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from kk.lib import connect, feed_after, follow, resume, run, submit

from .detect import HISTORY, LATEST, MAX, PROP, RESULT, anomalies, change_set

MODULE = "urn:kk:module:anomaly-recent"
AGENT = "urn:kk:agent:anomaly"
SCOPE = "urn:kk:scope:default"
COLUMNS = "id, subject, qualifiers, object_value, valid_from, valid_to"
PAGE = 1000
_CURSOR: dict[str, int] = {}


def entries_since(conn, cursor: int) -> tuple[int, list[set[str]]]:
    out = []
    while True:
        page = feed_after(conn, cursor, PAGE)
        if page:
            cursor = page[-1]["seq"]
        out += [{str(i) for i in e["claim_ids"] or []} for e in page if {RESULT, MAX} & set(e["predicates"] or [])]
        if len(page) < PAGE:
            return cursor, out


def read(cur, ids: list[str]) -> tuple[list[dict], list[dict], dict[str, tuple]]:
    """In one query: the windows to compare for every series the entries touched (the touched windows and the
    LATEST + HISTORY before or after them), the limits in force, and {touched id: (series, predicate, withdrawn)}."""
    cur.execute(f"""with t as (select id, subject, case when predicate = %(max)s then jsonb_build_object(%(prop)s::text, qualifiers->%(prop)s::text)
                                                       else qualifiers end as q, predicate, status = 'deprecated' as gone, valid_from
                               from api.claims where id = any(%(ids)s::uuid[]) and predicate in (%(res)s, %(max)s)),
                       s as (select subject, q, coalesce(min(valid_from) filter (where predicate = %(res)s and not gone),
                                                         'infinity') as t from t group by 1, 2)
                  select 'touched', t.id, t.subject, t.q, null::jsonb, null::timestamptz, null::timestamptz, t.predicate, t.gone from t
                  union all
                  select 'window', w.*, null::text, null::boolean from s cross join lateral (
                    (select {COLUMNS} from api.claims c where c.predicate = %(res)s and c.subject = s.subject
                        and c.qualifiers = s.q and c.valid_from >= s.t and c.status <> 'deprecated' and c.evidence_type = 'observed')
                    union all
                    (select {COLUMNS} from api.claims c where c.predicate = %(res)s and c.subject = s.subject
                        and c.qualifiers = s.q and c.valid_from < s.t and c.status <> 'deprecated' and c.evidence_type = 'observed'
                      order by c.valid_from desc limit %(n)s)) w
                  union all
                  select 'limit', {COLUMNS}, null, null from api.claims where predicate = %(max)s and status <> 'deprecated'""",
                {"ids": ids, "res": RESULT, "max": MAX, "prop": PROP, "n": LATEST + HISTORY})
    obs, limits, touched = [], [], {}
    for kind, i, subject, q, value, start, end, pred, gone in cur.fetchall():
        if kind == "touched":
            touched[str(i)] = ((subject, json.dumps(q, sort_keys=True)), pred, gone)
        else:
            (obs if kind == "window" else limits).append(
                {"id": i, "subject": subject, "qualifiers": q, "object_value": value, "valid_from": start, "valid_to": end})
    return obs, limits, touched


def one_pass(conn, seen: dict | None = None) -> dict:
    db = conn.info.dbname
    since = _CURSOR[db] if db in _CURSOR else resume(conn, MODULE)
    reached, entries = entries_since(conn, since)
    if not entries:
        _CURSOR[db] = reached
        return {"anomalies": {}}
    with conn.cursor() as cur:
        obs, limits, touched = read(cur, sorted(set().union(*entries)))
        key = lambda o: (o["subject"], json.dumps(o["qualifiers"], sort_keys=True))  # noqa: E731
        by_series: dict[tuple, list[dict]] = {}
        for o in sorted(obs, key=lambda o: o["valid_from"]):
            by_series.setdefault(key(o), []).append(o)
        check = set()
        for entry in entries:
            per: dict[tuple, list[dict]] = {}
            for o in obs:
                if str(o["id"]) in entry:
                    per.setdefault(key(o), []).append(o)
            for windows in per.values():
                check |= {str(o["id"]) for o in sorted(windows, key=lambda o: o["valid_from"])[-LATEST:]}
        for series, pred, gone in touched.values():
            if pred == MAX and not gone or pred == RESULT and gone:
                check |= {str(o["id"]) for o in by_series.get(series, [])[-LATEST:]}
        found = anomalies(obs, limits, check)
        if not found:
            _CURSOR[db] = reached
            return {"anomalies": {}}
        cur.execute("select idempotency_key from api.change_sets where idempotency_key = any(%s)",
                    ([f"anomaly:{a['iri']}" for a in found],))
        done = {r[0] for r in cur.fetchall()}
        new = [a for a in found if f"anomaly:{a['iri']}" not in done]
        submitted = {}
        with run(cur, MODULE, {"since": since}) as (run_id, outputs):
            for a in new:
                submitted[a["iri"]] = str(submit(cur, change_set(a, AGENT, SCOPE), run_id)["id"])
            outputs.update(anomalies=len(new), feed_seq=reached)
    _CURSOR[db] = reached
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
