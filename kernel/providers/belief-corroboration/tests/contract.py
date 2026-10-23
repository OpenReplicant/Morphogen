"""Runs the belief-model slot contract (kernel/contract/slots/belief-model) against this provider.
Prints "ok: <case id>" per passing case, as every provider runner does. No database needed.
Ported from rebuild 4 modules/belief-corroboration/tests/test_eval.py.
"""
import sys
from datetime import datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from belief_corroboration.model import Claim, score  # noqa: E402

SET = HERE.parents[2] / "contract" / "slots" / "belief-model"


def when(v):
    return datetime.fromisoformat(v) if v else None


def main() -> int:
    failed = 0
    for path in sorted((SET / "cases").glob("*.yaml")):
        case = yaml.safe_load(path.read_text())
        claims = [Claim(c["id"], c["key"], c["subject"], c["predicate"], c["object"], c["agent"],
                        frozenset(c["sources"]), when(c.get("valid_from")), when(c.get("valid_to")),
                        c.get("deprecated", False), c.get("entity"), tuple(c.get("refuted_by", ())),
                        c.get("undermined", False)) for c in case["input"]["claims"]]
        try:
            got = {k: v for k, (v, _) in score(claims, set(case["input"]["functional"])).items()}
        except Exception as e:  # a crash is a failed case, and the other cases still run
            failed += 1
            print(f"FAIL: {case['id']}: {type(e).__name__}: {e}")
            continue
        if got == case["expect"]["beliefs"]:
            print(f"ok: {case['id']}")
        else:
            failed += 1
            print(f"FAIL: {case['id']}: expected {case['expect']['beliefs']}, got {got}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
