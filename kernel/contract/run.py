"""Conformance check: runs each provider's runner and confirms it passed every contract case for
the slots it fills.

  record-store / write-pipeline / change-feed -> every case in invariants.yaml (needs PGHOST, PGUSER: a superuser)
  a slot with a set in slots/    -> every case file in slots/<slot>/cases

Usage: python3 kernel/contract/run.py [provider ...]   (default: every provider in kernel/providers)
A provider's runner (provider.yaml `runner`, run in its directory) prints "ok: <case>" at the start of a
line (or after a psql NOTICE prefix) per passing case. Fails on a slot that kernel/blueprint/slots.yaml
does not declare, a slot case set with no cases, or no providers at all.
"""
import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
PROVIDERS = HERE.parent / "providers"
SLOTS = {s["id"] for s in yaml.safe_load((HERE.parent / "blueprint" / "slots.yaml").read_text())["slots"]}
OK = re.compile(r"^(?:psql:\S+ NOTICE:\s+)?ok: (.+?)\s*$", re.M)


def expected(slots: list[str]) -> list[str]:
    spec = yaml.safe_load((HERE / "invariants.yaml").read_text())
    cases = []
    if set(slots) & set(spec["applies_to"]):
        cases += [c for inv in spec["invariants"].values() for c in inv["cases"]]
        cases += [c for k, sec in spec.items() if k != "invariants" and isinstance(sec, dict)
                  for c in sec.get("cases", [])]
    for slot in slots:
        d = HERE / "slots" / slot
        if d.is_dir():
            if yaml.safe_load((d / "set.yaml").read_text()).get("slot") != slot:
                raise SystemExit(f"slots/{slot}/set.yaml names another slot")
            found = [yaml.safe_load(p.read_text())["id"] for p in sorted((d / "cases").glob("*.yaml"))]
            if not found:
                raise SystemExit(f"slots/{slot} has no cases")
            cases += found
    return cases


def check(name: str) -> bool:
    d = PROVIDERS / name
    meta = yaml.safe_load((d / "provider.yaml").read_text())
    unknown = [s for s in meta["slots"] if s not in SLOTS]
    if unknown:
        print(f"{name}: FAIL: slots not in kernel/blueprint/slots.yaml: {unknown}")
        return False
    cases = expected(meta["slots"])
    if not cases:
        print(f"{name}: no contract cases for slots {meta['slots']}")
        return True
    cmd = shlex.split(meta["runner"])
    if cmd[0] == "python3":
        cmd[0] = sys.executable   # the interpreter that has the contract requirements
    out = subprocess.run(cmd, cwd=d, capture_output=True, text=True)
    log = out.stdout + out.stderr
    passed = set(OK.findall(log))
    missing = [c for c in cases if c not in passed]
    if out.returncode:
        print(log[-3000:])
        print(f"{name}: FAIL: runner exited {out.returncode}")
    for c in missing:
        print(f"{name}: MISSING: {c}")
    print(f"{name}: {len(cases) - len(missing)}/{len(cases)} contract cases passed")
    return not missing and out.returncode == 0


if __name__ == "__main__":
    names = sys.argv[1:] or sorted(p.name for p in PROVIDERS.iterdir()
                                   if (p / "provider.yaml").exists() and not p.name.startswith("_"))
    if not names:
        sys.exit("no providers found")
    results = [check(n) for n in names]
    sys.exit(0 if all(results) else 1)
