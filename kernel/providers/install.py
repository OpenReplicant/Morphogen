"""Install the record store and providers into a database, as a superuser.

  python3 kernel/providers/install.py <database> [provider ...]   (default: every provider with a migration)

Creates the database when missing, applies record-postgres's schema if the kernel schema is absent, then
each provider's migration.sql (each is idempotent). Uses the PG* environment, like psql.
Rebuild 4 did this with `kk init` and `kk module install`; the smaller `kk` command is still to write.
"""
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECORD = HERE / "record-postgres" / "schema"


def psql(db: str, *args: str) -> str:
    out = subprocess.run(["psql", "-d", db, "-v", "ON_ERROR_STOP=1", "-qAt", *args],
                         capture_output=True, text=True)
    if out.returncode:
        raise SystemExit(f"psql failed on {db}: {out.stderr.strip()[-800:]}")
    return out.stdout.strip()


def providers_with_migrations() -> list[str]:
    return sorted(p.name for p in HERE.iterdir() if (p / "migration.sql").exists() and not p.name.startswith("_"))


def install(db: str, names: list[str]) -> None:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", db):
        raise SystemExit(f"database name {db!r}: use lower-case letters, digits and underscores")
    if not psql("postgres", "-c", f"select 1 from pg_database where datname = '{db}'"):
        subprocess.run(["createdb", db], check=True)
    if not psql(db, "-c", "select 1 from pg_namespace where nspname = 'kernel'"):
        psql(db, "-f", str(RECORD / "001_kernel.sql"), "-f", str(RECORD / "002_bootstrap.sql"))
    for name in names:
        psql(db, "-f", str(HERE / name / "migration.sql"))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    install(sys.argv[1], sys.argv[2:] or providers_with_migrations())
