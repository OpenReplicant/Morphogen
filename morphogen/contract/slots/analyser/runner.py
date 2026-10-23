"""The analyser slot's own runner (set.yaml `runner:`): runs every case against one provider's
`<package>.detect.anomalies(observations, limits)`, the package being the one its service runs
(provider.yaml `service: python3 -m <package>`). Prints "ok: <case id>" per passing case. The slot owns
it, not the provider, so a candidate cannot certify itself (R5-21). No database needed.

  python3 runner.py <provider directory>
"""
import importlib
import re
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
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    provider = Path(sys.argv[1]).resolve()
    m = re.fullmatch(r"python3 -m ([a-z_][a-z0-9_]*)", str((yaml.safe_load((provider / "provider.yaml").read_text()) or {}).get("service", "")))
    if not m:
        print("FAIL: the provider's service must be python3 -m <package>")
        return 1
    sys.path.insert(0, str(provider))
    anomalies = importlib.import_module(f"{m.group(1)}.detect").anomalies
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
