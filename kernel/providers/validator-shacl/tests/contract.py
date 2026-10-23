"""Runs the validator slot contract (kernel/contract/slots/validator) against this provider.
Prints "ok: <case id>" per passing case, as every provider runner does. No database needed.
Ported from rebuild 4 modules/validator-shacl/tests/test_eval.py.
"""
import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from validator.core import validate  # noqa: E402

sys.path.insert(0, str(HERE.parent / "shapes" / "tests"))
import test_shapes  # noqa: E402  the shapes alone, as an export is checked against them

SET = HERE.parents[2] / "contract" / "slots" / "validator"


def reason_found(reason: str, report: dict) -> bool:
    if reason.startswith("schema: "):
        prefix = reason[len("schema: "):]
        return any(e["path"] == prefix or e["path"].startswith(prefix + "/") for e in report["schema_errors"])
    if reason.startswith("shape: "):
        return any(v["path"] == reason[len("shape: "):] for v in report["shape_violations"])
    return any(v["message"] == reason for v in report["shape_violations"])


def main() -> int:
    failed = 0
    for path in sorted((SET / "cases").glob("*.yaml")):
        case = yaml.safe_load(path.read_text())
        cs = json.loads((SET / case["input"]["change_set"]).read_text())
        try:
            ok, report = validate(cs, [tuple(t) for t in case["input"].get("context", [])])
        except Exception as e:  # a crash is a failed case, and the other cases still run
            failed += 1
            print(f"FAIL: {case['id']}: {type(e).__name__}: {e}")
            continue
        want = case["expect"]
        got = "valid" if ok else "invalid"
        if got != want["outcome"]:
            failed += 1
            print(f"FAIL: {case['id']}: expected {want['outcome']}, got {got}: {json.dumps(report)}")
        elif not ok and not reason_found(want["reason"], report):
            failed += 1
            print(f"FAIL: {case['id']}: reason {want['reason']!r} not in report: {json.dumps(report)}")
        else:
            print(f"ok: {case['id']}")
    for test in (test_shapes.test_valid_fixture_conforms, test_shapes.test_every_invalid_node_is_reported):
        try:
            test()
        except AssertionError as e:
            failed += 1
            print(f"FAIL: shapes: {test.__name__}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
