"""Install Morphogen into a database, as a superuser: the kernel and the kernel providers it uses, then
its own modules' migrations.

  python3 morphogen/modules/install.py <database> [module ...]   (default: every module with a migration)

Uses kernel/providers/install.py for the kernel part, and the PG* environment, like psql. A module's own
login (provider.yaml `login`, created by its migration) gets KK_LOGIN_PASSWORD as its password when that
is set (R5-22).
"""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("kernel_install", HERE.parents[1] / "kernel" / "providers" / "install.py")
kernel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kernel)

KERNEL_PROVIDERS = ["pack-loader", "validator-shacl", "belief-corroboration", "evaluator", "truth-maintenance"]


def modules() -> list[str]:
    return sorted(p.name for p in HERE.iterdir() if (p / "migration.sql").exists() and not p.name.startswith("_"))


def install(db: str, names: list[str]) -> None:
    kernel.install(db, KERNEL_PROVIDERS)
    for name in names:
        kernel.psql(db, "-f", str(HERE / name / "migration.sql"))
    pw = os.environ.get("KK_LOGIN_PASSWORD")
    for name in names:
        login = next((line.split(":", 1)[1].strip() for line in (HERE / name / "provider.yaml").read_text().splitlines()
                      if line.startswith("login:")), None)
        if login:                                     # the database revokes connect from public (kernel install)
            kernel.psql(db, "-c", f'grant connect on database "{db}" to "{login}"')
        if login and pw:                              # -f, so psql quotes the password (-c would not)
            with tempfile.NamedTemporaryFile("w", suffix=".sql") as f:
                f.write(f'alter role "{login}" password :\'pw\';\n')
                f.flush()
                kernel.psql(db, "-v", f"pw={pw}", "-f", f.name)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    install(sys.argv[1], sys.argv[2:] or modules())
