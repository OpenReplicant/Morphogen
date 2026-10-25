"""People who sign in to the UI (T21; rebuild 4 `kk person add`, D-74): a Postgres login of their own.

  python morphogen/ui/people.py add DB NAME        asks for the password (or reads it from a pipe; never an
                                                   argument: it would show in the process list and the history)
  python morphogen/ui/people.py remove DB NAME     at once: their tokens stop working and they can no longer sign in

A person is the login role `person_<name>` with a SCRAM password, a member of kk_reviewer (people review; the
store decides for which scopes, R5-05), granted to kk_authenticator so the UI's server may act as them once
Postgres has checked their password, and an agent `urn:kk:agent:person:<name>` of kind person. Uses the PG*
environment (a superuser). Postgres receives only a SCRAM verifier of the password, never the password itself, so
it is not in any statement log. Removing a person keeps their role and agent (their decisions stay attributed,
invariant 1) but takes it from kk_authenticator and disables its login.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "kernel" / "src"))

NAME = re.compile(r"[a-z][a-z0-9_]{0,30}")      # no '-': two names must never share a role


def role(name: str) -> str:
    return "person_" + name


def iri(name: str) -> str:
    return f"urn:kk:agent:person:{name}"


def add(conn, name: str, password: str, label: str | None = None) -> str:
    """Create (or reset the password of) the person `name` on a superuser connection; returns their agent IRI."""
    from psycopg import sql
    if not NAME.fullmatch(name):
        raise ValueError(f"name {name!r}: lower-case letters, digits and _, starting with a letter")
    if len(password) < 12:
        raise ValueError("a password of at least 12 characters")
    r, me = role(name), iri(name)
    other = conn.execute("select iri from kernel.agent where db_role = %s and iri <> %s", (r, me)).fetchone()
    if other:
        raise ValueError(f"{r} is already the login of {other[0]}")
    verifier = conn.pgconn.encrypt_password(password.encode(), r.encode(), b"scram-sha-256").decode()
    exists = conn.execute("select 1 from pg_roles where rolname = %s", (r,)).fetchone()
    conn.execute(sql.SQL("{} role {} login password {}").format(
        sql.SQL("alter" if exists else "create"), sql.Identifier(r), sql.Literal(verifier)))
    conn.execute(sql.SQL("grant kk_reviewer to {}").format(sql.Identifier(r)))
    conn.execute(sql.SQL("grant {} to kk_authenticator").format(sql.Identifier(r)))
    conn.execute("set role kk_owner")
    conn.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, %s, 'person', %s) "
                 "on conflict (iri) do nothing", (me, r, label or name))
    conn.execute("reset role")
    return me


def remove(conn, name: str) -> None:
    """Stop `name` signing in and acting, at once: the server can no longer switch to their role (their tokens
    fail on the next call) and the login is disabled. Their role and agent stay, so what they did stays theirs."""
    from psycopg import sql
    r = role(name)
    if not NAME.fullmatch(name) or not conn.execute("select 1 from pg_roles where rolname = %s", (r,)).fetchone():
        raise ValueError(f"no person {name!r}")
    conn.execute(sql.SQL("revoke {} from kk_authenticator").format(sql.Identifier(r)))
    conn.execute(sql.SQL("alter role {} nologin").format(sql.Identifier(r)))


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ("add", "remove"):
        sys.exit(__doc__)
    from kk.lib import connect
    with connect(url=f"dbname={sys.argv[2]}") as su:
        if sys.argv[1] == "remove":
            remove(su, sys.argv[3])
        else:
            import getpass
            pw = getpass.getpass(f"password for {sys.argv[3]}: ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n")
            print(add(su, sys.argv[3], pw))
