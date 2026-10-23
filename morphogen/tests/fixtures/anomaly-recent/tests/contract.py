"""Runs the analyser slot contract (morphogen/contract/slots/analyser) against this provider.
Prints "ok: <case id>" per passing case, as every provider runner does. No database needed.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from anomaly_recent.detect import MAX, PROP, anomalies  # noqa: E402

SET = Path(os.environ.get("KK_CASES") or HERE.parents[2] / "contract" / "slots" / "analyser")   # run.py sets KK_CASES
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def claims(case: dict):
    obs = [{"id": o["id"], "subject": o["target"], "qualifiers": {PROP: o["property"], **(o.get("extra") or {})},
            "object_value": {"@value": o["value"]}, "valid_from": T0 + timedelta(minutes=o["window"]),
            "valid_to": T0 + timedelta(minutes=o["window"] + 1)} for o in case["input"]["observations"]]
    limits = [{"id": x["id"], "subject": x["target"], "predicate": MAX, "qualifiers": {PROP: x["property"]},
               "object_value": {"@value": x["value"]}} for x in case["input"]["limits"]]
    return obs, limits


def summary(found: list[dict], limit_ids: set) -> list[dict]:
    out = []
    for a in found:
        kind = a["kind"].rsplit(":", 1)[-1]
        row = {"kind": kind, "target": a["target"], "observation": a["premises"][0]}
        if kind == "limit":
            row["limit"] = next(p for p in a["premises"] if p in limit_ids)
        out.append(row)
    return sorted(out, key=lambda r: (r["target"], r["observation"], r["kind"]))


def main() -> int:
    failed = 0
    paths = sorted((SET / "cases").glob("*.yaml"))
    if not paths:
        print(f"FAIL: no cases in {SET}")
        return 1
    for path in paths:
        case = yaml.safe_load(path.read_text())
        obs, limits = claims(case)
        want = sorted(case["expect"]["anomalies"], key=lambda r: (r["target"], r["observation"], r["kind"]))
        try:
            got = summary(anomalies(obs, limits), {x["id"] for x in limits})
        except Exception as e:  # a crash is a failed case, and the other cases still run
            failed += 1
            print(f"FAIL: {case['id']}: {type(e).__name__}: {e}")
            continue
        if got == want:
            print(f"ok: {case['id']}")
        else:
            failed += 1
            print(f"FAIL: {case['id']}: expected {want}, got {got}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
