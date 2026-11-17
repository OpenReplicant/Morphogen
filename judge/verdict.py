"""Assemble a verdict from the judge's own per-case measurements and check it against the schema."""

from datetime import datetime, timezone

from . import schemas, stats


def _select(ids, selectors):
    out = []
    for s in selectors:
        out += [i for i in ids if (i.startswith(s[:-1]) if s.endswith("*") else i == s)]
    return sorted(set(out))


def decide(*, repository, base, candidate, judge, card, policy, case_ids, served, measured,
           outputs=None, correct=None, reported=None, pull_request=None, seed=None, admission=()):
    """measured: {"base": {kpi: {case: value}}, "candidate": {...}}, all measured by the judge.
    outputs: {"base": {case: output}, "candidate": {...}} for must_not_change; correct: {case: bool}
    for the candidate, for must_pass. admission: reasons admission gave, if any."""
    seed = stats.new_rng().getrandbits(63) if seed is None else seed
    rng = stats.new_rng(seed)
    alpha = policy["alpha"]
    rules = policy["case_sets"].get(card.get("cases", {}).get("set"), {})
    ids = sorted(case_ids)
    v = {
        "verdict": "morphogen.verdict/v1", "repository": repository, "base": base, "candidate": candidate,
        "card_sha256": schemas.sha256(card), "policy_sha256": schemas.sha256(policy), "judge": judge,
        "cases": {"set": card.get("cases", {}).get("set", ""), "version": card.get("cases", {}).get("version", ""),
                  "expected": len(ids), "served": served, "stale": served > rules.get("stale_after", float("inf"))},
        "alpha": alpha, "seed": seed, "kpis": [], "reported": reported or {},
        "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if pull_request is not None:
        v["pull_request"] = pull_request
    if admission:
        return schemas.check("verdict", {**v, "decision": "refuse", "reason": "not admitted: " + "; ".join(admission)})
    for k in card["kpis"]:
        v["kpis"].append(stats.judge_kpi(k, ids, measured["base"].get(k["name"], {}),
                                         measured["candidate"].get(k["name"], {}), alpha, rng))
    tests = card.get("tests", {})
    mp, mnc = _select(ids, tests.get("must_pass", [])), _select(ids, tests.get("must_not_change", []))
    outputs, correct = outputs or {"base": {}, "candidate": {}}, correct or {}
    v["tests"] = {
        "must_pass": {"checked": len(mp), "failed": [i for i in mp if not correct.get(i)][:50]},
        "must_not_change": {"checked": len(mnc), "failed": [
            i for i in mnc if i not in outputs["candidate"] or outputs["candidate"][i] != outputs["base"].get(i)][:50]},
    }
    missing = [s for s in tests.get("must_pass", []) + tests.get("must_not_change", []) if not _select(ids, [s])]
    results = [k["result"] for k in v["kpis"]]
    if "stop" in results and "refuse" not in results:
        k = next(k for k in v["kpis"] if k["result"] == "stop")
        decision, reason = "stop", f"{k['name']}: {k['reason']}"
    elif "refuse" in results:
        k = next(k for k in v["kpis"] if k["result"] == "refuse")
        decision, reason = "refuse", f"{k['name']}: {k['reason']}"
    elif missing:
        decision, reason = "refuse", f"card's tests name cases the set does not have: {missing}"
    elif v["tests"]["must_pass"]["failed"]:
        decision, reason = "refuse", f"must-pass cases failed: {v['tests']['must_pass']['failed']}"
    elif v["tests"]["must_not_change"]["failed"]:
        decision, reason = "refuse", f"must-not-change cases changed: {v['tests']['must_not_change']['failed']}"
    elif v["cases"]["stale"]:
        decision, reason = "stop", f"case set has served {served} verdicts, past its limit of {rules['stale_after']}"
    else:
        decision, reason = "pass", "; ".join(f"{k['name']}: {k['reason']}" for k in v["kpis"])
    return schemas.check("verdict", {**v, "decision": decision, "reason": reason})
