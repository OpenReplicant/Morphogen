"""Lane policy checks: the autonomy matrix routes plans; irreversible changes always go to a person.
No database (the store's side, review forced for plan steps, is checked in morphogen/tests/test_loop.py).

  python3 tests/test_lane.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "morphogen" / "src"))
from morphogen.policy import actions, autonomy, level, route  # noqa: E402

INTENT = ROOT / "morphogen" / "intent"


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg)


p = autonomy(INTENT)
check(level(p, "urn:kk:module:planner") == "L1", "every module starts at L1")
check(route(p, "L1", "low") == "review", "L1: a low-risk plan still needs a person")
check(route(p, "L3", "low") == "auto" and route(p, "L3", "high") == "review", "L3: low applies, high waits")
check(all(route(p, lv, "irreversible") == "review" for lv in p["matrix"]), "irreversible always needs a person")
check(route(p, "L0", "low") == "review", "L0 reports: never auto")
try:
    route(p, "L9", "low")
    check(False, "an unknown level is an error")
except ValueError:
    check(True, "an unknown level is an error, not a lane")
a = actions(INTENT)
check(all({"kind", "risk", "answers"} <= set(v) for v in a.values())
      and all({"setting", "min", "max"} <= set(v) for v in a.values() if v["kind"] == "setting"),
      "every action has a kind, a risk and what it answers; settings have bounds")
