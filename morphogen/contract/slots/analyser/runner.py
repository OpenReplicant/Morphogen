"""The analyser slot's own runner (set.yaml `runner:`): runs every case against one provider's
`<package>.detect.anomalies(observations, limits)`, the package being the one its service runs
(provider.yaml `service: python3 -m <package>`). Prints "ok: <case id>" per passing case. The slot owns
it, not the provider, so a candidate cannot certify itself (R5-21): the provider's code runs in a child
process that gets every case's input and answers with its anomalies as JSON; this process, which never
imports it, judges them and prints the results. No database needed. A case with a
`then:` stage is checked twice: on its input, and on the input after `then` (observations retracted,
limits superseded), which must give `then.expect`.

  python3 runner.py <provider directory>
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

SET = Path(__file__).resolve().parent
MAX = "https://www.irit.fr/recherches/MELODI/ontologies/BBO#maxValue"
PROP = "http://www.w3.org/ns/sosa/observedProperty"
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def claims(case: dict):
    obs = [{"id": o["id"], "subject": o["target"], "qualifiers": {PROP: o["property"], **(o.get("extra") or {})},
            "object_value": {"@value": o["value"]}, "valid_from": T0 + timedelta(minutes=o["window"]),
            "valid_to": T0 + timedelta(minutes=o["window"] + 1)} for o in case["input"]["observations"]]
    limits = [{"id": x["id"], "subject": x["target"], "predicate": MAX, "qualifiers": {PROP: x["property"]},
               "object_value": {"@value": x["value"]}} for x in case["input"]["limits"]]
    return obs, limits


def after(case: dict) -> dict:
    """The case's input once its `then` stage is applied."""
    then = case["then"]
    gone = set(then.get("retract") or []) | {x["supersedes"] for x in then.get("limits") or [] if x.get("supersedes")}
    new = [{k: v for k, v in x.items() if k != "supersedes"} for x in then.get("limits") or []]
    return {"input": {"observations": [o for o in case["input"]["observations"] if o["id"] not in gone],
                      "limits": [x for x in case["input"]["limits"] if x["id"] not in gone] + new}}


def summary(found: list[dict], limit_ids: set) -> list[dict]:
    out = []
    for a in found:
        kind = a["kind"].rsplit(":", 1)[-1]
        row = {"kind": kind, "target": a["target"], "observation": a["premises"][0] if a["premises"] else None}
        if kind == "limit":
            row["limit"] = next((p for p in a["premises"] if p in limit_ids), None)
        out.append(row)
    return sorted(out, key=lambda r: (r["target"], r["observation"], r["kind"]))


CHILD = """
import importlib, json, os, sys
from datetime import datetime
out = os.fdopen(os.dup(1), "w")
os.dup2(2, 1)                                            # the provider's own prints go to stderr
sys.path.insert(0, sys.argv[1])
anomalies = importlib.import_module(sys.argv[2] + ".detect").anomalies
answers = []
for stage in json.load(sys.stdin):
    for o in stage["obs"]:
        o["valid_from"], o["valid_to"] = datetime.fromisoformat(o["valid_from"]), datetime.fromisoformat(o["valid_to"])
    try:
        answers.append({"found": [{"kind": a["kind"], "target": a["target"], "premises": [str(x) for x in a["premises"]]}
                                  for a in anomalies(stage["obs"], stage["limits"])]})
    except Exception as e:
        answers.append({"error": f"{type(e).__name__}: {e}"})
out.write(json.dumps(answers))
"""


def answer(provider: Path, package: str, stages: list[tuple[list, list]]) -> list[dict]:
    """The provider's anomalies for each (observations, limits), from a child process."""
    data = [{"obs": [{**o, "valid_from": o["valid_from"].isoformat(), "valid_to": o["valid_to"].isoformat()} for o in obs],
             "limits": limits} for obs, limits in stages]
    out = subprocess.run([sys.executable, "-c", CHILD, str(provider), package], input=json.dumps(data),
                         capture_output=True, text=True, timeout=300)
    try:
        got = json.loads(out.stdout)
        assert isinstance(got, list) and len(got) == len(stages)
        return got
    except (ValueError, AssertionError):
        return [{"error": f"no answer (exit {out.returncode}): {out.stderr.strip()[-300:]}"}] * len(stages)


def main() -> int:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    provider = Path(sys.argv[1]).resolve()
    m = re.fullmatch(r"python3 -m ([a-z_][a-z0-9_]*)", str((yaml.safe_load((provider / "provider.yaml").read_text()) or {}).get("service", "")))
    if not m:
        print("FAIL: the provider's service must be python3 -m <package>")
        return 1
    try:                                                 # the child cannot reach this process's stdout through /proc
        import ctypes
        ctypes.CDLL(None).prctl(4, 0, 0, 0, 0)          # PR_SET_DUMPABLE 0
    except (OSError, AttributeError):
        pass
    failed = 0
    paths = sorted((SET / "cases").glob("*.yaml"))
    if not paths:
        print(f"FAIL: no cases in {SET}")
        return 1
    cases = [yaml.safe_load(path.read_text()) for path in paths]
    plan = [(case, [(state, expect) for state, expect in
                    [(case, case["expect"])] + ([(after(case), case["then"]["expect"])] if case.get("then") else [])])
            for case in cases]
    answers = iter(answer(provider, m.group(1), [claims(state) for _, stages in plan for state, _ in stages]))
    for case, stages in plan:
        want, got, error = [], [], None
        for state, expect in stages:
            a = next(answers)
            want.append(sorted(expect["anomalies"], key=lambda r: (r["target"], r["observation"], r["kind"])))
            if "error" in a:
                error = error or a["error"]
            else:
                got.append(summary(a["found"], {x["id"] for x in state["input"]["limits"]}))
        if error:                                        # a crash is a failed case, and the other cases still run
            failed += 1
            print(f"FAIL: {case['id']}: {error}")
            continue
        if got == want:
            print(f"ok: {case['id']}")
        else:
            failed += 1
            print(f"FAIL: {case['id']}: expected {want}, got {got}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
