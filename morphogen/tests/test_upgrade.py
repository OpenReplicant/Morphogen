"""An intent repository an earlier `up` made is upgraded (R5-48): where it ran map-gaps, the local environment now runs
the kernel's gap finder, committed as a bootstrap; a repository already upgraded, or never running map-gaps, is left
as it is. No database needed.

  python3 morphogen/tests/test_upgrade.py
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "morphogen" / "deploy"))
os.environ.setdefault("MORPHOGEN_OPERATOR_NAME", "upgrade test")
os.environ.setdefault("MORPHOGEN_OPERATOR_EMAIL", "upgrade@test")
import local  # noqa: E402


def check(cond, msg):
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


with tempfile.TemporaryDirectory() as t:
    d = Path(t)
    env = d / "environments" / local.ENV
    env.mkdir(parents=True)
    (env / "map-gaps.yaml").write_text("provider: map-gaps\nservice: python3 -m map_gaps\ncwd: morphogen/modules/map-gaps\n")
    local.git(d, "init", "-q")
    local.git(d, "add", "-A")
    local.git(d, "commit", "-qm", "bootstrap")
    local.upgrade(d)
    new = env / "gaps-shacl.yaml"
    log = local.git(d, "log", "--format=%s").splitlines()
    check(not (env / "map-gaps.yaml").exists() and new.exists() and "cwd: kernel/providers/gaps-shacl" in new.read_text()
          and "service: python3 -m gaps_shacl" in new.read_text() and log[0].startswith("bootstrap: the kernel's gap finder"),
          "an earlier repository runs the kernel's gap finder in place of map-gaps, committed as a bootstrap")
    check(not local.git(d, "status", "--porcelain").strip(), "and nothing is left uncommitted")
    local.upgrade(d)
    check(len(local.git(d, "log", "--format=%s").splitlines()) == len(log), "an upgraded repository is left as it is")
print("upgrade tests passed")
