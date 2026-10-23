"""packs.sql is current (regenerated from kernel/packs it is byte-identical) and, installed, approves every
property the providers write, references and attributes every pack claim (tests/check_packs.sql).

  PGHOST=... PGUSER=<superuser> python3 kernel/providers/pack-loader/tests/test_packs.py
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROVIDER = HERE.parent
sys.path.insert(0, str(PROVIDER.parent))
import install  # noqa: E402

DB = "kk_packs_test"


def main() -> None:
    fresh = subprocess.run([sys.executable, "-m", "pack_loader"], cwd=PROVIDER, capture_output=True, text=True, check=True)
    if fresh.stdout != (PROVIDER / "packs.sql").read_text():
        raise SystemExit("CHECK FAILED: packs.sql is stale: python -m pack_loader > packs.sql")
    print("ok: packs.sql matches kernel/packs")
    subprocess.run(["dropdb", "--if-exists", "--force", DB], check=True)
    install.install(DB, ["pack-loader"])
    out = subprocess.run(["psql", "-d", DB, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(HERE / "check_packs.sql")],
                         capture_output=True, text=True)
    print(out.stderr.strip().replace("psql:" + str(HERE / "check_packs.sql"), "").strip())
    subprocess.run(["dropdb", "--force", DB], check=True)
    if out.returncode or "PACK CHECKS PASSED" not in out.stdout:
        raise SystemExit("CHECK FAILED: pack checks")
    print("ALL PACK TESTS PASSED")


if __name__ == "__main__":
    main()
