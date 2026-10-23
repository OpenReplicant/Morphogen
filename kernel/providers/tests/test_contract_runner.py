"""kernel/contract/run.py's rules (R5-21): every slot declares its contract; a declared case set must exist
and have cases; none only for an unfilled slot; provider-tests is a declared gap. No database.

  python3 kernel/providers/tests/test_contract_runner.py
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("contract_run", ROOT / "contract" / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg)


def refused(text: str) -> bool:
    d = Path(tempfile.mkdtemp())
    (d / "bp.yaml").write_text(text)
    try:
        run.expected(["s"], [d / "bp.yaml"])
    except SystemExit:
        return True
    return False


check(refused("slots:\n  - {id: s, default: p}\n"), "a slot with no contract is refused")
check(refused("slots:\n  - {id: s, default: p, contract: none}\n"), "contract none with a default provider is refused")
check(refused("slots:\n  - {id: s, default: p, contract: nowhere}\n"), "a contract path that does not exist is refused")
d = Path(tempfile.mkdtemp())
(d / "set").mkdir()
(d / "set" / "cases").mkdir()
(d / "set" / "set.yaml").write_text("slot: s\n")
(d / "bp.yaml").write_text("slots:\n  - {id: s, default: p, contract: set}\n")
try:
    run.expected(["s"], [d / "bp.yaml"])
    check(False, "an empty case set is refused")
except SystemExit:
    check(True, "an empty case set is refused")
(d / "set" / "cases" / "a.yaml").write_text("id: urn:x:case/a\n")
check(run.expected(["s"], [d / "bp.yaml"]) == ["urn:x:case/a"], "a case set's cases, relative to the blueprint")
(d / "gap.yaml").write_text("slots:\n  - {id: s, default: p, contract: provider-tests}\n  - {id: u, default: none, contract: none}\n")
check(run.expected(["s", "u"], [d / "gap.yaml"]) == [], "provider-tests and none: no shared cases")
kernel = run.contracts(run.BLUEPRINTS)
check(all(c is not None for c in kernel.values()) and str(kernel["validator"]).endswith("contract/slots/validator"),
      "every kernel slot declares its contract")
