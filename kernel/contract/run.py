"""Conformance check: runs each provider's runner and confirms it passed every contract case for the
slots it fills. Each slot's contract is declared in its blueprint (`contract:`, R5-21):

  a .yaml file (invariants.yaml)  -> every case it names (the record store, write pipeline, change feed)
  a directory with set.yaml        -> every case file in <dir>/cases (kernel/contract/slots/<slot>)
  provider-tests                   -> no shared cases yet: only the provider's own tests (a declared gap; refused by a
                                      blueprint with `cases_required: true`, as the kernel's is)
  none                             -> an unfilled slot (default: none); declared when a provider fills it

Paths are relative to the blueprint file. Usage:

  python3 kernel/contract/run.py [--blueprint FILE]... [--providers DIR] [provider ...]

Defaults: the kernel's blueprint and kernel/providers. A distribution passes its own as well, e.g.
`--blueprint kernel/blueprint/slots.yaml --blueprint <distribution>.yaml --providers <its modules>`.
A provider's runner (provider.yaml `runner`, run in its directory, with KK_CASES naming the slot's case
set directory when there is one) prints "ok: <case>" at the start of a line (or after a psql NOTICE
prefix) per passing case. A case set may name its own runner (set.yaml `runner:`, relative to the set,
run with the provider's directory as its argument): that set is run by its runner, never the provider's, so a
provider cannot certify itself (R5-21); a provider filling several slots runs every one of their contracts. Fails on a slot two blueprints declare, a provider slot no blueprint
declares, a slot with no `contract:`, a contract path that does not exist, a case set with no cases, a provider whose
slot has cases but no runner, or no providers at all. Lists the slots whose contract is provider-tests.
"""
import argparse
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
KERNEL = HERE.parent
OK = re.compile(r"^(?:psql:\S+ NOTICE:\s+)?ok: (.+?)\s*$", re.M)
SPECIAL = {"provider-tests", "none"}


def contracts(blueprints: list[Path]) -> dict[str, object]:
    """slot -> its contract: a resolved Path, or "provider-tests" / "none". Raises on a missing field."""
    out: dict[str, object] = {}
    for bp in blueprints:
        spec = yaml.safe_load(bp.read_text())
        for s in spec["slots"]:
            c = s.get("contract")
            if c is None:
                raise SystemExit(f"{bp}: slot {s['id']} declares no contract (a case set, provider-tests or none)")
            if c == "provider-tests" and spec.get("cases_required"):
                raise SystemExit(f"{bp}: slot {s['id']} has no shared case set (provider-tests), which this blueprint refuses")
            if s["id"] in out:
                raise SystemExit(f"{bp}: slot {s['id']} is already declared by another blueprint")
            if c == "none" and s.get("default") not in ("none", None):
                raise SystemExit(f"{bp}: slot {s['id']} has a default provider but contract none")
            out[s["id"]] = c if c in SPECIAL else (bp.parent / c).resolve()
    return out


def cases_of(slot: str, contract) -> list[str]:
    if contract in SPECIAL:
        return []
    path = Path(contract)
    if not path.exists():
        raise SystemExit(f"slot {slot}: contract {path} does not exist")
    if path.is_file():
        spec = yaml.safe_load(path.read_text())
        return ([c for inv in spec["invariants"].values() for c in inv["cases"]]
                + [c for k, sec in spec.items() if k != "invariants" and isinstance(sec, dict) for c in sec.get("cases", [])])
    if yaml.safe_load((path / "set.yaml").read_text()).get("slot") != slot:
        raise SystemExit(f"{path}/set.yaml names another slot")
    found = [yaml.safe_load(p.read_text())["id"] for p in sorted((path / "cases").glob("*.yaml"))]
    if not found:
        raise SystemExit(f"{path} has no cases")
    return found


BLUEPRINTS = [KERNEL / "blueprint" / "slots.yaml"]


def expected(slots: list[str], blueprints: list[Path] = None) -> list[str]:
    """Every contract case a provider of `slots` must pass (each contract once)."""
    table = contracts(blueprints or BLUEPRINTS)
    seen, cases = set(), []
    for slot in slots:
        c = table.get(slot)
        if c is None or str(c) in seen:
            continue
        seen.add(str(c))
        cases += cases_of(slot, c)
    return cases


def check(d: Path, blueprints: list[Path]) -> bool:
    """Run every contract of the slots a provider fills: each case set with a runner of its own through that runner
    (so the provider cannot certify itself), the rest through the provider's runner once."""
    name = d.name
    meta = yaml.safe_load((d / "provider.yaml").read_text())
    table = contracts(blueprints)
    unknown = [s for s in meta["slots"] if s not in table]
    if unknown:
        print(f"{name}: FAIL: slots no blueprint declares: {unknown}")
        return False
    groups: dict[str, tuple] = {}
    for s in meta["slots"]:
        if table[s] not in SPECIAL:
            groups.setdefault(str(table[s]), (table[s], s))
    if not groups:
        print(f"{name}: no contract cases for slots {meta['slots']} (provider-tests)")
        return True
    cmds, theirs, cases = [], [], []
    for contract, slot in groups.values():
        cases += cases_of(slot, contract)
        path = Path(contract)
        own = path.is_dir() and (yaml.safe_load((path / "set.yaml").read_text()) or {}).get("runner")
        if own:
            cmds.append(([sys.executable, str(path / own), str(d.resolve())], {}))
        else:
            theirs.append(path)
    if theirs:
        if not meta.get("runner"):
            print(f"{name}: FAIL: slots {meta['slots']} have contract cases but the provider has no runner")
            return False
        cmd = shlex.split(meta["runner"])
        if cmd[0] == "python3":
            cmd[0] = sys.executable   # the interpreter that has the contract requirements
        sets = [p for p in theirs if p.is_dir()]
        cmds.append((cmd, {"KK_CASES": str(sets[0])} if len(sets) == 1 else {}))
    passed, ok = set(), True
    for cmd, extra in cmds:
        out = subprocess.run(cmd, cwd=d, capture_output=True, text=True, env={**os.environ, **extra})
        log = out.stdout + out.stderr
        passed |= set(OK.findall(log))
        if out.returncode:
            print(log[-3000:])
            print(f"{name}: FAIL: {Path(cmd[1]).name if len(cmd) > 1 else cmd[0]} exited {out.returncode}")
            ok = False
    missing = [c for c in cases if c not in passed]
    for c in missing:
        print(f"{name}: MISSING: {c}")
    print(f"{name}: {len(cases) - len(missing)}/{len(cases)} contract cases passed")
    return ok and not missing


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run every provider's contract cases.")
    ap.add_argument("--blueprint", action="append", type=Path, help="a blueprint or distribution file (repeatable)")
    ap.add_argument("--providers", type=Path, default=KERNEL / "providers")
    ap.add_argument("names", nargs="*")
    a = ap.parse_args(argv)
    blueprints = [p.resolve() for p in a.blueprint] if a.blueprint else BLUEPRINTS
    dirs = [a.providers / n for n in a.names] if a.names else sorted(
        p for p in a.providers.iterdir() if (p / "provider.yaml").exists() and not p.name.startswith("_"))
    if not dirs:
        print("no providers found")
        return 1
    table = contracts(blueprints)
    gaps = sorted(s for s, c in table.items() if c == "provider-tests")
    results = [check(d, blueprints) for d in dirs]
    print(f"slots with no shared case set yet (provider-tests): {', '.join(gaps) or 'none'}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
