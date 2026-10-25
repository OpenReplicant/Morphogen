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

# A slot declared by two blueprints is refused: a distribution cannot redeclare a kernel slot's contract.
(d / "again.yaml").write_text("slots:\n  - {id: s, default: q, contract: provider-tests}\n")
try:
    run.contracts([d / "bp.yaml", d / "again.yaml"])
    check(False, "a slot two blueprints declare is refused")
except SystemExit:
    check(True, "a slot two blueprints declare is refused")

# A case set's own runner is used instead of the provider's: a provider cannot certify itself.
(d / "set" / "set.yaml").write_text("slot: s\nrunner: runner.py\n")
(d / "set" / "runner.py").write_text("import sys, pathlib\nprint('ok: urn:x:case/a' if (pathlib.Path(sys.argv[1]) / 'good').exists() else 'FAIL')\n")
prov = d / "providers" / "p"
prov.mkdir(parents=True)
(prov / "provider.yaml").write_text("id: urn:kk:provider:p\nslots: [s]\nrunner: python3 claims.py\n")
(prov / "claims.py").write_text("print('ok: urn:x:case/a')\n")
check(not run.check(prov, [d / "bp.yaml"]), "a provider whose own runner prints every case still fails the slot's runner")
(prov / "good").write_text("")
check(run.check(prov, [d / "bp.yaml"]), "the slot's runner, given the provider's directory, passes it")

# A blueprint with cases_required refuses provider-tests (the kernel's does, T25): every slot has shared cases.
check(refused("cases_required: true\nslots:\n  - {id: s, default: p, contract: provider-tests}\n"),
      "provider-tests is refused where cases are required")
check(not refused("cases_required: true\nslots:\n  - {id: s, default: none, contract: none}\n"),
      "an unfilled slot is allowed where cases are required")
check("provider-tests" not in {str(c) for c in kernel.values()}, "no kernel slot is left with provider-tests")

# A provider filling two slots runs both contracts: the slot's own runner, and its own runner for the other set.
(d / "other").mkdir()
(d / "other" / "cases").mkdir()
(d / "other" / "set.yaml").write_text("slot: t\n")
(d / "other" / "cases" / "b.yaml").write_text("id: urn:x:case/b\n")
(d / "two.yaml").write_text("slots:\n  - {id: s, default: p, contract: set}\n  - {id: t, default: p, contract: other}\n")
(prov / "provider.yaml").write_text("id: urn:kk:provider:p\nslots: [s, t]\nrunner: python3 claims.py\n")
(prov / "claims.py").write_text("print('ok: urn:x:case/b')\n")
check(run.check(prov, [d / "two.yaml"]), "both contracts of a provider that fills two slots are run")
(prov / "claims.py").write_text("print('nothing')\n")
check(not run.check(prov, [d / "two.yaml"]), "a provider missing the other slot's cases fails, though the first slot's runner passes it")
