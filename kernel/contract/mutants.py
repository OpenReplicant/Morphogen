"""Mutation check: each mutant breaks one guarantee in a copy of a provider (<providers>/_mutant) and
the contract must fail on it. A provider lists its mutants in tests/mutants.py as
MUTANTS = [(name, file relative to the provider, [(old, new), ...]), ...]; each old text must occur once.
A provider of a slot with no case set (provider-tests) may list mutants too: its own tests (provider.yaml
`tests`, run in the copy) must fail on each.

Usage: PGHOST=... PGUSER=<superuser> python3 kernel/contract/mutants.py [--blueprint FILE]... [--providers DIR]
       [provider ...] [-k name filter]
--blueprint and --providers are passed to run.py (defaults: the kernel's). Exits non-zero if the unmutated
provider fails or any mutant passes.
"""
import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROVIDERS = HERE.parent / "providers"
BLUEPRINTS: list[Path] = []
MUT = PROVIDERS / "_mutant"


def contract(name: str) -> subprocess.CompletedProcess:
    args = [a for bp in BLUEPRINTS for a in ("--blueprint", str(bp))] + ["--providers", str(PROVIDERS)]
    return subprocess.run([sys.executable, str(HERE / "run.py"), *args, name], capture_output=True, text=True)


def own_tests(name: str) -> subprocess.CompletedProcess:
    """A provider-tests provider's own tests, run in its directory; the first failure stops them."""
    import yaml
    out = subprocess.CompletedProcess([], 0, "", "")
    for t in yaml.safe_load((PROVIDERS / name / "provider.yaml").read_text()).get("tests", []):
        out = subprocess.run([sys.executable, *t.split()[1:]] if t.startswith("python3 ") else ["sh", "-c", t],
                             cwd=PROVIDERS / name, capture_output=True, text=True)
        if out.returncode:
            break
    return out


def has_cases(name: str) -> bool:
    spec = importlib.util.spec_from_file_location("contract_run", HERE / "run.py")
    run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run)
    meta = run.yaml.safe_load((PROVIDERS / name / "provider.yaml").read_text())
    return bool(run.expected(meta["slots"], BLUEPRINTS or None))


def mutants_of(name: str) -> list:
    path = PROVIDERS / name / "tests" / "mutants.py"
    if not path.exists():
        return []
    spec = importlib.util.spec_from_file_location(f"mutants_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.MUTANTS


def main(names: list[str], pattern: str) -> int:
    survivors, total = [], 0
    for name in names:
        listed = mutants_of(name)
        cases = has_cases(name)
        if not cases and not listed:
            continue   # nothing in the contract to kill a mutant with; the provider's own tests cover it
        check = contract if cases else own_tests
        if not listed and not pattern:
            print(f"{name}: FAIL: no tests/mutants.py; every provider with contract cases needs mutants")
            return 2
        mutants = [m for m in listed if pattern in m[0]]
        if not mutants:
            continue
        # A mutant "fails" for any reason, including no database: the unmutated provider must pass first.
        base = check(name)
        if base.returncode:
            print(f"{name}: the unmutated provider fails {'the contract' if cases else 'its own tests'}; "
                  "fix that (or the connection) first")
            print(base.stdout[-1500:] + base.stderr[-500:])
            return 2
        for label, rel, edits in mutants:
            total += 1
            if MUT.exists():
                shutil.rmtree(MUT)
            shutil.copytree(PROVIDERS / name, MUT, ignore=shutil.ignore_patterns("__pycache__"))
            p = MUT / rel
            s = p.read_text()
            for old, new in edits:
                assert s.count(old) == 1, (name, label, old)
                s = s.replace(old, new)
            p.write_text(s)
            out = check("_mutant")
            why = [l for l in (out.stdout + out.stderr).splitlines()
                   if re.search(r"MISSING|CHECK FAILED|FAIL", l)]
            print(("FAILS (good)" if out.returncode else "PASSES (bad)"), f"- {name}: {label}")
            for line in why[:2]:
                print("     ", line[-160:])
            if not out.returncode:
                survivors.append(f"{name}: {label}")
    if MUT.exists():
        shutil.rmtree(MUT)
    print(f"{total - len(survivors)}/{total} mutants fail the contract (or, without cases, the provider's tests)")
    if not total:
        print("FAIL: no mutant ran")
        return 1
    return 1 if survivors else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    pattern = ""
    for flag in ("-k", "--blueprint", "--providers"):
        while flag in args:
            i = args.index(flag)
            value = args[i + 1]
            del args[i:i + 2]
            if flag == "-k":
                pattern = value
            elif flag == "--blueprint":
                BLUEPRINTS.append(Path(value).resolve())
            else:
                PROVIDERS = Path(value).resolve()
                MUT = PROVIDERS / "_mutant"
    names = args or sorted(p.name for p in PROVIDERS.iterdir()
                           if (p / "provider.yaml").exists() and not p.name.startswith("_"))
    sys.exit(main(names, pattern))
