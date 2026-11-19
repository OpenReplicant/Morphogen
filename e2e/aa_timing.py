"""A/A for timing: identical code on both sides, wall time as a *deciding* KPI. How often does the judge
call the candidate faster? It should be at most alpha. Compares the two orderings rep by rep:
`blocked` (all base cases, then all candidate cases: the judge before DECISIONS row 29) and `paired`
(judge.run.run_pairs: both sides per case, order by coin flip).

    python e2e/aa_timing.py --checkout e2e/toy --module topwords --image IMAGE --reps 20 --cases 30
"""

import argparse
import io
import json
import random
import secrets
from pathlib import Path

from judge import run, stats

KPI = {"name": "wall_seconds", "source": "runner", "direction": "lower", "floor": 0.0, "role": "decide"}


def once(mode, tags, module, cases, limits):
    out = {"base": io.StringIO(), "candidate": io.StringIO()}
    if mode == "paired":
        run.run_pairs(tags, module, cases, limits, out)
    else:
        for side in run.SIDES:
            for c in cases:
                rec = run.run_case(tags[side], module, json.dumps(c["input"]).encode(), limits)
                out[side].write(json.dumps({"id": c["id"], **rec}) + "\n")
    wall = {s: {json.loads(l)["id"]: json.loads(l)["wall_seconds"] for l in out[s].getvalue().splitlines()}
            for s in run.SIDES}
    r = stats.judge_kpi(KPI, [c["id"] for c in cases], wall["base"], wall["candidate"], 0.05, stats.new_rng())
    return r["result"] == "pass", r["p_value"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkout", required=True, type=Path)
    ap.add_argument("--module", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--cases", type=int, default=30)
    a = ap.parse_args()
    rng = random.Random(0)
    words = "alpha beta gamma delta epsilon zeta eta theta".split()
    cases = [{"id": f"c{i:02d}", "input": {"text": " ".join(rng.choice(words) for _ in range(300)), "k": 3}}
             for i in range(a.cases)]
    limits = {"cpus": "1", "memory": "512m", "timeout": 30}
    tags = {s: f"mg-aa-{s}-{secrets.token_hex(4)}" for s in run.SIDES}
    try:
        for s in run.SIDES:
            run.build(a.checkout, a.image, tags[s])  # the same code, two images, as in a real run
        passes = {"blocked": 0, "paired": 0}
        for i in range(a.reps):
            for mode in (("blocked", "paired") if i % 2 == 0 else ("paired", "blocked")):
                ok, p = once(mode, tags, a.module, cases, limits)
                passes[mode] += ok
                print(json.dumps({"rep": i, "mode": mode, "pass": ok, "p": round(p, 4)}), flush=True)
        print(json.dumps({"reps": a.reps, "false_pass": {m: n / a.reps for m, n in passes.items()}}), flush=True)
    finally:
        for t in tags.values():
            run.docker("rmi", "-f", t)


if __name__ == "__main__":
    main()
