"""Trusted stage: score both runs' outputs against the held-out answers and write the verdict.

Runs inside the trusted job, which never runs the candidate's code: it reads the run records as data,
and the only code it imports is the base's own scorer. Each KPI is measured here: `scorer` KPIs from
the base's scorer, `runner` KPIs from the harness's records.

The base's scorer is `.morphogen/scorer.py` on the base, with `score(input, answer, output)` returning
{"correct": bool, <kpi>: number, ...}; `output` is the program's stdout, or None if it failed.
"""

import argparse
import json
import runpy
from pathlib import Path

from . import schemas, verdict

RUNNER_KPIS = {"wall_seconds", "cpu_seconds"}  # measured by the base's harness, never the program


def read_cases(path):
    cases = {}
    for line in path.read_text().splitlines():
        if line.strip():
            c = schemas.loads_strict(line)
            if c["id"] in cases:
                raise SystemExit(f"case set has duplicate id {c['id']!r}")
            cases[c["id"]] = c
    return cases


def read_run(path):
    """A run's records by case id. Malformed or duplicated records count as not seen."""
    recs, dup = {}, set()
    if not path.exists():
        return recs
    for line in path.read_text(errors="replace").splitlines():
        try:
            r = schemas.loads_strict(line)
            cid = r["id"]
            float(r["wall_seconds"]), float(r["cpu_seconds"]), int(r["exit"])
        except (ValueError, KeyError, TypeError):
            continue
        if cid in recs:
            dup.add(cid)
        recs[cid] = r
    return {k: v for k, v in recs.items() if k not in dup}


def measure(run, cases, score):
    kpis, outputs, correct = {}, {}, {}
    for cid, case in cases.items():
        r = run.get(cid)
        if r is None:
            continue
        ok = r["exit"] == 0 and not r.get("timed_out") and not r.get("oom")
        out = r["output"] if ok else None
        outputs[cid] = out
        s = score(case["input"], case["answer"], out)
        correct[cid] = bool(s.get("correct"))
        for k, v in s.items():
            if k != "correct":
                kpis.setdefault(k, {})[cid] = float(v)
        for k in RUNNER_KPIS:
            kpis.setdefault(k, {})[cid] = float(r[k])
    return kpis, outputs, correct


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-checkout", required=True, type=Path)
    ap.add_argument("--cases-dir", required=True, type=Path, help="held-out case sets: <set>/cases.jsonl")
    ap.add_argument("--base-run", required=True, type=Path)
    ap.add_argument("--candidate-run", required=True, type=Path)
    ap.add_argument("--admission", required=True, type=Path)
    ap.add_argument("--served", required=True, type=int)
    ap.add_argument("--repository", required=True)
    ap.add_argument("--pull-request", type=int)
    ap.add_argument("--base-sha", required=True)
    ap.add_argument("--head-sha", required=True)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    policy = schemas.check("policy", schemas.loads_strict((a.base_checkout / ".morphogen/policy.json").read_text()))
    adm = json.loads(a.admission.read_text())
    card = adm["card"] or {}
    judged = adm.get("judged", True)
    refused = adm["refused"] or not card
    cases = {} if refused else read_cases(a.cases_dir / card["cases"]["set"] / "cases.jsonl")
    score = runpy.run_path(str(a.base_checkout / ".morphogen/scorer.py"))["score"]
    common = dict(repository=a.repository, base=a.base_sha, candidate=a.head_sha, judge=a.base_sha, card=card,
                  policy=policy, case_ids=list(cases), served=a.served, pull_request=a.pull_request)
    if not judged:
        v = verdict.decide(**common, measured={"base": {}, "candidate": {}}, admission=adm["refused"], judged=False)
    elif refused:
        v = verdict.decide(**common, measured={"base": {}, "candidate": {}}, admission=adm["refused"] or ["no card"])
    else:
        bk, bo, _ = measure(read_run(a.base_run), cases, score)
        ck, co, cc = measure(read_run(a.candidate_run), cases, score)
        v = verdict.decide(**common, measured={"base": bk, "candidate": ck},
                           outputs={"base": bo, "candidate": co}, correct=cc)
    a.out.write_bytes(schemas.canonical(v))
    print(json.dumps({k: v[k] for k in ("decision", "reason")}, indent=2))


if __name__ == "__main__":
    main()
