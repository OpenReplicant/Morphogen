"""A provider process's environment when it runs code that was not reviewed (a candidate) or that has a
login of its own: its own database login, and none of its parent's credentials (R5-22).

A provider declares, in the provider.yaml of the reviewed incumbent, the role it acts as (`role:`) and a
login that may switch only to it (`login:`, created by its migration). The login's password, if the
cluster asks for one, is KK_LOGIN_PASSWORD (set at deploy time, as kk_authenticator's is). A candidate is
given the incumbent's login: it acts with exactly the incumbent's rights.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from psycopg.conninfo import make_conninfo

KEEP = {"PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR", "PGHOST", "PGPORT", "PGSSLMODE"}


def login_of(provider_dir: Path) -> tuple[str, str] | None:
    """(role, login) the provider declares, or None."""
    f = provider_dir / "provider.yaml"
    meta = (yaml.safe_load(f.read_text()) or {}) if f.exists() else {}
    return (meta["role"], meta["login"]) if meta.get("role") and meta.get("login") else None


def login_env(base_url: str, role: str, login: str, extra: dict) -> dict:
    """The allow-listed environment, DATABASE_URL for the login (on base_url's database) and KK_ROLE,
    plus `extra` (PYTHONPATH, OTEL_*, the provider's KK_* settings)."""
    pw = os.environ.get("KK_LOGIN_PASSWORD")
    url = make_conninfo(base_url, user=login, **({"password": pw} if pw else {}))
    return {**{k: v for k, v in os.environ.items() if k in KEEP}, **extra, "DATABASE_URL": url, "KK_ROLE": role}
