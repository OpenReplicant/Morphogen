"""Install Morphogen into a database, as a superuser: the kernel and the kernel providers it uses, then
its own modules' migrations.

  python3 morphogen/modules/install.py <database> [module ...]   (default: every module with a migration)

Uses kernel/providers/install.py for the kernel part, and the PG* environment, like psql.
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("kernel_install", HERE.parents[1] / "kernel" / "providers" / "install.py")
kernel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kernel)

KERNEL_PROVIDERS = ["pack-loader", "validator-shacl", "belief-corroboration"]


def modules() -> list[str]:
    return sorted(p.name for p in HERE.iterdir() if (p / "migration.sql").exists() and not p.name.startswith("_"))


def install(db: str, names: list[str]) -> None:
    kernel.install(db, KERNEL_PROVIDERS)
    for name in names:
        kernel.psql(db, "-f", str(HERE / name / "migration.sql"))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    install(sys.argv[1], sys.argv[2:] or modules())
