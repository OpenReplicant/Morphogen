"""Planner (the Plan step of MAPE-K): whenever the change feed carries anomalies (and every
KK_SWEEP_SECONDS) it plans for each new limit anomaly from the fixed action list (plan.py), with a
prediction and a risk class, and submits the plan in the lane the autonomy policy gives it (the store
forces review for plan steps today). It never acts; the intent actuator carries out approved steps.

  python -m planner [--once]

A target gets one open plan at a time: an anomaly is planned for only if no plan of this planner on the
same target is waiting for review or still without a verdict, and only if its window starts after the target's latest plan
was recorded (anomalies from before a change are what the change answered). Plans are keyed by their
anomaly, so a restart submits nothing twice (R5-18).
A node of a managed system (urn:kk:node:<system>:<service>, R5-25) is planned for on the map: the
anomalous node first, then the nodes it connects to (kkt:connectsTo, breadth first, as recorded by the
agents in KK_MAP_AGENTS), and the step goes to the first whose compose file sets the action's setting;
the connections followed join the plan's premises.
Env: DATABASE_URL (a login that may SET ROLE to KK_ROLE), KK_ROLE (default kkm_planner), KK_INTENT_DIR
(the intent directory, default morphogen/intent), KK_INTENT_ENV (default sandbox), KK_SWEEP_SECONDS,
KK_MAP_AGENTS (comma-separated; default urn:kk:agent:encoder-compose).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml

from kk.lib import connect, follow, run, submit
from morphogen.experiments import ROOT, experiment_id, provider_slots, run_name
from morphogen import systems
from morphogen.policy import actions, autonomy, level, route

from .plan import (DCT_TYPE, MAX, OA, PART_OF, PPLAN, RESULT, SOSA, applies_to, build_request, change_set, choose,
                   proposal, replace_change_set, replacement)

MODULE = "urn:kk:module:planner"
AGENT = "urn:kk:agent:planner"
SCOPE = "urn:kk:scope:default"
EVALUATOR = "urn:kk:agent:evaluator"
BUILDER = "urn:kk:agent:builder"
DQV = "http://www.w3.org/ns/dqv#"
BENCHMARKS = ROOT / "morphogen" / "contract" / "slots"
CONNECTS_TO = "https://w3id.org/knowledge-kernel/tosca#connectsTo"
COLUMNS = "id, subject, predicate, object_entity, object_value, qualifiers, valid_from, valid_to, recorded_at, scope"


def rows(cur, q: str, args=()) -> list[dict]:
    cur.execute(q, args)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def number(v):
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def setting(intent: Path, env: str, target: str, name: str):
    """The current value of `name` in the target provider's intent file, or None."""
    f = intent / "environments" / env / (target.rsplit(":", 1)[-1] + ".yaml")
    if not target.startswith("urn:kk:provider:") or not f.exists():
        return None
    return number(((yaml.safe_load(f.read_text()) or {}).get("env") or {}).get(name))


def same_system(a: str, b: str) -> bool:
    ma, mb = systems.NODE.fullmatch(a or ""), systems.NODE.fullmatch(b or "")
    return bool(ma and mb and ma.group(1) == mb.group(1))


def on_map(cur, intent: Path, start: str, name: str, mappers: list[str]):
    """(node, current value, ids of the connections followed) for the first node from `start`, then the
    nodes it connects to, breadth first, whose compose file sets `name`; None when there is none."""
    seen, queue = {start}, [(start, [])]
    while queue:
        node, via = queue.pop(0)
        current = number(systems.setting(intent, node, name))
        if current is not None:
            return node, current, via
        for r in rows(cur, """select object_entity, id::text as id from api.claims where subject = %s and predicate = %s
                              and attributed_to = any(%s) and status <> 'deprecated' order by object_entity""",
                      (node, CONNECTS_TO, list(mappers))):
            if r["object_entity"] not in seen and same_system(r["object_entity"], start):
                seen.add(r["object_entity"])
                queue.append((r["object_entity"], via + [r["id"]]))
    return None


def one_pass(conn, intent: Path, env: str, mappers: list[str] = ("urn:kk:agent:encoder-compose",)) -> dict:
    acts, policy = actions(intent), autonomy(intent)
    lane = lambda risk: route(policy, level(policy, MODULE), risk)
    report = {}
    with conn.cursor() as cur:
        claims = rows(cur, f"""select {COLUMNS} from api.claims where subject like 'urn:kk:anomaly:%%'
                               and status <> 'deprecated'""")
        anomalies: dict[str, dict] = {}
        for c in claims:
            a = anomalies.setdefault(c["subject"], {"iri": c["subject"], "claim_ids": [], "kind": None,
                                                    "target": None, "valid_from": c["valid_from"], "scope": c["scope"]})
            a["claim_ids"].append(str(c["id"]))
            if c["predicate"] == DCT_TYPE:
                a["kind"] = c["object_entity"]
            elif c["predicate"] == OA + "hasTarget":
                a["target"] = c["object_entity"]
        # This planner's plans per target: when recorded, and whether a verdict closed them.
        # (A plan holds both the target its step changes and the one its prediction is about.)
        plans = rows(cur, """select s.object_entity as target, p.object_entity as plan, s.recorded_at
                             from api.claims s join api.claims p on p.subject = s.subject
                             where s.predicate = %s and p.predicate = %s and s.attributed_to = %s
                               and s.status <> 'deprecated' and p.status <> 'deprecated'
                             union all
                             select subject, qualifiers->>%s, recorded_at from api.claims
                             where predicate = %s and qualifiers ? %s and attributed_to = %s and status <> 'deprecated'""",
                     (SOSA + "hasFeatureOfInterest", PPLAN + "isStepOfPlan", AGENT, PART_OF, MAX, PART_OF, AGENT))
        # This planner's plan change sets: those on their way (submitted, validated, waiting for a person)
        # hold their target; any plan already proposed for an anomaly, whatever became of it (rejected,
        # invalid), is not proposed again: the person who rejected it gets a new plan only from a new anomaly.
        mine_sets = rows(cur, """select c.status, r.info->>'target' as target, r.info->>'step_target' as step_target,
                                        r.info->>'anomaly' as anomaly,
                                        r.info->>'request' as request, c.idempotency_key as key
                                 from api.change_sets c join kernel.run r on r.id = c.generated_by
                                 where c.attributed_to = %s and (c.idempotency_key like 'plan:%%'
                                                                 or c.idempotency_key like 'request:%%')""", (AGENT,))
        pending = {t for r in mine_sets if r["status"] in ("submitted", "valid", "awaiting_review", "approved")
                   for t in (r["target"], r["step_target"]) if t}
        proposed = {r["anomaly"] for r in mine_sets}
        replaced = {r["request"] for r in mine_sets if r["key"].startswith("plan:") and r["request"]}
        closed = {r["object_entity"] for r in rows(cur, """select object_entity from api.claims
                    where predicate = %s and subject like 'urn:kk:verdict:%%' and status <> 'deprecated'""", (OA + "hasTarget",))}
        for a in sorted(anomalies.values(), key=lambda a: (a["valid_from"] is None, a["valid_from"])):
            if not a["target"] or not a["kind"] or a["iri"] in proposed:
                continue
            if a["scope"] != SCOPE:
                report[a["iri"]] = {"none": f"the anomaly is in {a['scope']}; this planner plans in {SCOPE} only"}
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
            if {obs["scope"], lim["scope"]} != {SCOPE}:
                report[a["iri"]] = {"none": f"its premises are not all in {SCOPE}"}
                continue
            prop = (obs["qualifiers"] or {}).get(SOSA + "observedProperty")
            chosen = choose(acts, prop, on=applies_to(a["target"]))
            if chosen is None and choose(acts, prop, "request"):
                report[a["iri"]] = request_for(cur, a, obs, lim, pending)
                continue
            target, current, via = a["target"], None, []
            if chosen and applies_to(a["target"]) == "node":
                target, current, via = on_map(cur, intent, a["target"], chosen[1]["setting"], mappers) or (target, None, [])
            elif chosen:
                current = setting(intent, env, a["target"], chosen[1]["setting"])
            got = proposal(a, obs, lim, current, acts, target, via)
            if "none" in got:
                report[a["iri"]] = got
                continue
            p = got["plan"]
            with run(cur, MODULE, {"anomaly": a["iri"], "target": a["target"], "step_target": p["target"]},
                     used=p["premises"]) as (run_id, outputs):
                res = submit(cur, change_set(p, AGENT, SCOPE, lane(p["risk"])), run_id)
                outputs.update(plan=p["iri"], change_set=str(res["id"]))
            report[a["iri"]] = {"plan": p["iri"], "change_set": str(res["id"]), "lane": res["lane"], "label": p["label"]}
            pending |= {a["target"], p["target"]}
        for r in my_requests(cur):
            if r["iri"] not in replaced:
                report[r["iri"]] = replace_for(cur, r, lane)
    return report


def request_for(cur, a: dict, obs: dict, lim: dict, pending: set) -> dict:
    """A build request for the anomaly's provider, if its slot has a benchmark and no request for it is open."""
    slots = [x for x in provider_slots(a["target"]) if (BENCHMARKS / x / "benchmark.yaml").exists()]
    if not slots:
        return {"none": f"{a['target']} fills no slot with a benchmark: nothing can be measured"}
    if a["target"] in pending or any(r["target"] == a["target"] for r in my_requests(cur)):
        return {"none": f"a build request for {a['target']} is already open"}
    cs = build_request(a, obs, lim, slots[0], AGENT, SCOPE)
    with run(cur, MODULE, {"anomaly": a["iri"], "target": a["target"]}, used=cs["ops"][0]["derived_from"]) as (run_id, outputs):
        res = submit(cur, cs, run_id)
        outputs.update(request=cs["ops"][0]["subject"], change_set=str(res["id"]))
    pending.add(a["target"])
    return {"request": cs["ops"][0]["subject"], "change_set": str(res["id"]), "lane": res["lane"]}


def my_requests(cur) -> list[dict]:
    """This planner's build requests: iri, target, slot, claim ids, and the limit they answer."""
    claims = rows(cur, f"""select {COLUMNS} from api.claims where subject like 'urn:kk:request:%%'
                           and attributed_to = %s and status <> 'deprecated'""", (AGENT,))
    out: dict[str, dict] = {}
    for c in claims:
        r = out.setdefault(c["subject"], {"iri": c["subject"], "claim_ids": []})
        r["claim_ids"].append(str(c["id"]))
        if c["predicate"] == OA + "hasTarget":
            r["target"] = c["object_entity"]
        elif c["predicate"] == "http://purl.org/dc/terms/subject":
            r["slot"] = c["object_entity"].removeprefix("urn:kk:slot:")
    for r in out.values():
        prem = rows(cur, f"""select {COLUMNS} from api.claims where predicate = %s and id in
                             (select derived_from from kernel.claim_derivation where claim_id = any(%s::uuid[]))""",
                    (MAX, r["claim_ids"]))
        r["limit"] = prem[0] if prem else None
    return [r for r in out.values() if r.get("target") and r.get("slot") and r.get("limit")]


def measured(cur, suite: str, run: str) -> dict | None:
    """The evaluator's measurements of one sandbox run: provider, contract passed and total, metric mean."""
    subject = f"urn:kk:eval:{suite}:{run}"
    got = rows(cur, """select id, predicate, object_entity, object_value, qualifiers from api.claims
                       where subject = %s and attributed_to = %s and status <> 'deprecated'""", (subject, EVALUATOR))
    if not got:
        return None
    metric = lambda name: next((float(c["object_value"]["@value"]) for c in got
                                if (c["qualifiers"] or {}).get(DQV + "isMeasurementOf") == f"urn:kk:metric:{suite}:{name}"), None)
    provider = next((c["object_entity"] for c in got if c["predicate"] == "http://purl.org/dc/terms/subject"), None)
    passed, total = metric("contract.passed"), metric("contract.total")
    if provider is None or passed is None or total is None:
        return None
    return {"provider": provider, "passed": int(passed), "total": int(total), "mean": metric("metric.mean"),
            "claim_ids": [str(c["id"]) for c in got]}


def replace_for(cur, r: dict, lane) -> dict:
    exp = experiment_id(r["iri"])
    suite = f"sandbox-{r['slot']}"
    inc, cand = measured(cur, suite, run_name(exp, "incumbent")), measured(cur, suite, run_name(exp, "candidate"))
    if inc is None or cand is None:
        return {"wait": "the sandbox has not measured the candidate and the incumbent yet"}
    if inc["provider"] != r["target"]:
        return {"none": f"the incumbent measured is {inc['provider']}, not {r['target']}"}
    built = rows(cur, """select id from api.claims where subject = %s and attributed_to = %s and status <> 'deprecated'""",
                 (cand["provider"], BUILDER))
    if not built:
        return {"wait": f"the builder has not recorded {cand['provider']}"}
    refs = rows(cur, "select source_uri from api.claim_references where claim_id = any(%s::uuid[])", ([str(b["id"]) for b in built],))
    shas = {m.group(1) for r in refs if (m := re.search(r"#sha256=([0-9a-f]{64})$", r["source_uri"] or ""))}
    if len(shas) != 1:
        return {"none": f"the builder recorded {len(shas)} content hashes for {cand['provider']}, not one"}
    cand = {**cand, "claim_ids": cand["claim_ids"] + [str(b["id"]) for b in built], "sha256": shas.pop()}
    got = replacement(r, inc, cand, r["limit"])
    if "none" in got:
        return got
    p = got["plan"]
    with run(cur, MODULE, {"request": r["iri"], "target": r["target"]}, used=p["premises"]) as (run_id, outputs):
        res = submit(cur, replace_change_set(p, AGENT, SCOPE, lane(p["risk"])), run_id)
        outputs.update(plan=p["iri"], change_set=str(res["id"]))
    return {"plan": p["iri"], "change_set": str(res["id"]), "lane": res["lane"], "label": p["label"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Plan for anomalies over a documented limit.")
    ap.add_argument("--once", action="store_true", help="one pass, print the result and exit")
    a = ap.parse_args(argv)
    intent = Path(os.environ.get("KK_INTENT_DIR", "morphogen/intent")).resolve()
    env = os.environ.get("KK_INTENT_ENV", "sandbox")
    conn = connect(os.environ.get("KK_ROLE", "kkm_planner"))
    mappers = [x.strip() for x in os.environ.get("KK_MAP_AGENTS", "urn:kk:agent:encoder-compose").split(",") if x.strip()]
    step = lambda c: print(json.dumps(one_pass(c, intent, env, mappers), default=str), flush=True)
    if a.once:
        step(conn)
        return 0
    follow(conn, step, wake=lambda e: any(p in (e["predicates"] or []) for p in (DCT_TYPE, OA + "hasTarget", DQV + "value")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
