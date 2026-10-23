"""Every provider's own tests (provider.yaml `tests`, run in its directory), then the end-to-end service
test. The contract (kernel/contract/run.py) is separate: it checks guarantees, these check each provider.

  PGHOST=... PGUSER=<superuser> python3 kernel/providers/test.py
"""
import os
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ENV = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(HERE.parent / "src"), os.environ.get("PYTHONPATH")]))}


def main() -> int:
    failed = []
    commands = []
    for d in sorted(p for p in HERE.iterdir() if (p / "provider.yaml").exists() and not p.name.startswith("_")):
        for t in yaml.safe_load((d / "provider.yaml").read_text()).get("tests", []):
            commands.append((d, t))
    commands += [(HERE, f"python3 {t.relative_to(HERE)}") for t in sorted((HERE / "tests").glob("test_*.py"))]
    for d, t in commands:
        cmd = shlex.split(t)
        if cmd[0] == "python3":
            cmd[0] = sys.executable
        out = subprocess.run(cmd, cwd=d, env=ENV, capture_output=True, text=True)
        print(("ok  " if out.returncode == 0 else "FAIL"), f"{d.name}: {t}")
        if out.returncode:
            print((out.stdout + out.stderr)[-2000:])
            failed.append(f"{d.name}: {t}")
    print(f"{len(commands) - len(failed)}/{len(commands)} provider test commands passed")
    return 1 if failed or not commands else 0


if __name__ == "__main__":
    sys.exit(main())
