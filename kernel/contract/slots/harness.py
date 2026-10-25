"""Shared by the kernel's slot runners (set.yaml `runner:`): a fresh record to run one provider against, as
the provider will run in a real install, and nothing of the provider imported here (R5-21).

  rec = Record("kkc_verifier", [provider_dir, ...])   # a new database: the kernel schema, the packs, each provider's migration
  role = rec.agent("kkc_extractor", "urn:kk:agent:contract-extractor")
  cs = rec.submit(role, ops)                         # a change set under a run of `role`, validated by the record's own
                                                     # validator (not the slot under test), applied when its lane is auto
  rec.service_once(provider_dir)                     # the provider's service, one pass (KK_ONCE=1), as its own role
  rec.rows("select ...", args)                       # as the superuser; role= to read as someone else
  rec.drop()

A provider's service connects through a login of its own that may SET ROLE only to the provider's role (provider.yaml
`role:`), never as the superuser, so what it reads and writes is what its role may; a role that is a superuser, holds
an elevated kernel role (kk_owner, kk_validator, kk_reviewer, kk_steward) or is not an agent (kk_agent) is refused.
Uses the PG* environment, like psql. Every name is derived from the database name, so two different sets can run side
by side; the same set cannot (its database and roles have fixed names), so run one mutants.py or run.sh at a time.

For trusted providers only: the provider's code runs as the same OS user as this harness, which holds the superuser's
credentials, so a hostile provider could connect as the superuser itself and fake its cases. A candidate written by
a model must run the contract confined (a distribution's sandbox runs it as a run user with no PG* environment, so a
kernel slot's cases fail safe there); never hand this harness a database for an unconfined candidate.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

import psycopg
import yaml
from psycopg import sql
from psycopg.types.json import Jsonb

HERE = Path(__file__).resolve().parent
KERNEL = HERE.parents[1]
SCHEMA = KERNEL / "providers" / "record-postgres" / "schema"
PACKS = KERNEL / "providers" / "pack-loader"
SCOPE = "urn:kk:scope:default"


def meta(provider: Path) -> dict:
    return yaml.safe_load((Path(provider) / "provider.yaml").read_text())


def package(provider: Path) -> str:
    """The package a provider's service or command runs (`python3 -m <package>`)."""
    m = meta(provider)
    for key in ("service", "command"):
        found = re.search(r"python3 -m ([A-Za-z_][\w.]*)", str(m.get(key) or ""))
        if found:
            return found.group(1)
    raise SystemExit(f"{provider}: provider.yaml names no `python3 -m <package>` service or command")


def check(cond: bool, case: str, detail: str = "") -> bool:
    """Print `ok: <case>` (what kernel/contract/run.py counts) or a failure with its detail."""
    print(f"ok: {case}" if cond else f"FAIL: {case}{': ' + detail if detail else ''}", flush=True)
    return bool(cond)


class Record:
    def __init__(self, db: str, providers: list[Path] = (), packs: bool = True, schema: Path = SCHEMA):
        if not re.fullmatch(r"kkc_[a-z0-9_]+", db):
            raise SystemExit(f"database name {db!r}: kkc_ then lower-case letters, digits and underscores")
        self.db = db
        self.passwords: dict[str, str] = {}
        self.made: list[str] = []      # the roles this record created, dropped with it
        subprocess.run(["dropdb", "--if-exists", "--force", db], check=True, capture_output=True)
        subprocess.run(["createdb", db], check=True)
        self.psql("-f", str(schema / "001_kernel.sql"), "-f", str(schema / "002_bootstrap.sql"))
        self.psql("-c", f'revoke connect on database "{db}" from public')
        if packs and not any(Path(p).resolve() == PACKS.resolve() for p in providers):
            self.psql("-f", str(PACKS / "migration.sql"))
        for p in providers:
            if (Path(p) / "migration.sql").exists():
                self.psql("-f", str(Path(p) / "migration.sql"))
        self.su = psycopg.connect(dbname=db, autocommit=True)
        self.validator = self.agent(f"{db}_validator", "urn:kk:agent:contract-validator", grants=("kk_validator",))

    # ------------------------------------------------------------------ setup
    def psql(self, *args: str) -> str:
        out = subprocess.run(["psql", "-d", self.db, "-v", "ON_ERROR_STOP=1", "-qAt", *args], capture_output=True, text=True)
        if out.returncode:
            raise SystemExit(f"psql failed on {self.db}: {out.stderr.strip()[-800:]}")
        return out.stdout.strip()

    def agent(self, role: str, iri: str, kind: str = "software", grants: tuple[str, ...] = ("kk_agent",)) -> str:
        """A role mapped to an agent, granted `grants`."""
        with self.su.cursor() as cur:
            cur.execute("select 1 from pg_roles where rolname = %s", (role,))
            if not cur.fetchone():
                cur.execute(sql.SQL("create role {} nologin").format(sql.Identifier(role)))
            if role.startswith("kkc_") and role not in self.made:
                self.made.append(role)
            for g in grants:
                cur.execute(sql.SQL("grant {} to {}").format(sql.Identifier(g), sql.Identifier(role)))
            cur.execute("set role kk_owner")
            cur.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, %s, %s, %s) on conflict do nothing",
                        (iri, role, kind, iri.rsplit(":", 1)[-1]))
            cur.execute("reset role")
        return role

    def agent_login(self, role: str, iri: str, grants: tuple[str, ...] = ("kk_agent",)) -> str:
        """An agent whose role is itself a login (as an agent harness signs in): a connection string for it."""
        self.agent(role, iri, grants=grants)
        pw = self.passwords.setdefault(role, secrets.token_hex(16))
        with self.su.cursor() as cur:
            cur.execute(sql.SQL("alter role {} login password {}").format(sql.Identifier(role), sql.Literal(pw)))
            cur.execute(sql.SQL("grant connect on database {} to {}").format(sql.Identifier(self.db), sql.Identifier(role)))
        where = {k: os.environ[e] for k, e in (("host", "PGHOST"), ("port", "PGPORT")) if os.environ.get(e)}
        return psycopg.conninfo.make_conninfo(dbname=self.db, user=role, password=pw, **where)

    def login(self, role: str) -> str:
        """A connection string for a login of its own that may SET ROLE only to `role`."""
        name = f"{self.db}_l_{re.sub(r'[^a-z0-9_]', '_', role)}"[:63]
        if name not in self.passwords:
            pw = secrets.token_hex(16)
            with self.su.cursor() as cur:
                cur.execute("select 1 from pg_roles where rolname = %s", (name,))
                verb = "alter" if cur.fetchone() else "create"
                cur.execute(sql.SQL(verb + " role {} login noinherit password {}").format(sql.Identifier(name), sql.Literal(pw)))
                cur.execute(sql.SQL("grant {} to {}").format(sql.Identifier(role), sql.Identifier(name)))
                cur.execute(sql.SQL("grant connect on database {} to {}").format(sql.Identifier(self.db), sql.Identifier(name)))
            self.passwords[name] = pw
        where = {k: os.environ[e] for k, e in (("host", "PGHOST"), ("port", "PGPORT")) if os.environ.get(e)}
        return psycopg.conninfo.make_conninfo(dbname=self.db, user=name, password=self.passwords[name], **where)

    def connect(self, role: str) -> psycopg.Connection:
        conn = psycopg.connect(self.login(role), autocommit=True)
        conn.execute(sql.SQL("set role {}").format(sql.Identifier(role)))
        return conn

    def scope(self, iri: str, readers: tuple[str, ...] = ("kk_agent",)) -> str:
        """A scope `readers` may read and write (each a role); the record's own validator may too."""
        readers = (*readers, self.validator)
        with self.su.cursor() as cur:
            cur.execute("set role kk_owner")
            cur.execute("insert into kernel.scope(iri, label) values (%s, %s) on conflict do nothing", (iri, iri))
            for r in readers:
                cur.execute("insert into kernel.scope_grant(scope, db_role, can_read, can_write) values (%s, %s, true, true) "
                            "on conflict do nothing", (iri, r))
            cur.execute("reset role")
        return iri

    def redact(self, claim_id: str) -> None:
        """Redact a claim's content as a steward (kk_steward)."""
        steward = self.agent(f"{self.db}_steward", "urn:kk:agent:contract-steward", kind="person", grants=("kk_steward",))
        with self.connect(steward) as conn, conn.cursor() as cur:
            cur.execute("select api.start_run(null, null, '[]', '{}')")
            run_id = cur.fetchone()[0]
            cur.execute("select api.redact('claim', %s, 'contract case', %s)", (claim_id, run_id))
            cur.execute("select api.finish_run(%s, 'succeeded')", (run_id,))

    # ------------------------------------------------------------------ the write path
    def submit(self, role: str, ops: list[dict], scope: str = SCOPE, key: str | None = None,
               module: str = "urn:kk:module:contract", lane: str | None = None) -> dict:
        """One change set by `role` under a run of its own; validated and (in the auto lane) applied."""
        with self.connect(role) as conn, conn.cursor() as cur:
            cur.execute("select api.start_run(%s, null, '[]', '{}')", (module,))
            run_id = str(cur.fetchone()[0])
            agent = cur.execute("select kernel.my_agent()").fetchone()[0]
            cs = {"idempotency_key": key or f"contract:{secrets.token_hex(8)}", "attributed_to": agent,
                  "generated_by": run_id, "target_scope": scope, "ops": ops, **({"lane": lane} if lane else {})}
            got = cur.execute("select api.submit_change_set(%s)", (Jsonb(cs),)).fetchone()[0]
            cur.execute("select api.finish_run(%s, 'succeeded')", (run_id,))
        self.validate()
        return {**got, "status": self.rows("select status from kernel.change_set where id = %s", (got["id"],))[0]["status"]}

    def validate(self) -> int:
        """Pass every submitted change set as the record's own validator: the slot under test is never asked to judge
        the change sets the cases rely on."""
        ids = [r["id"] for r in self.rows("select id from kernel.change_set where status = 'submitted' order by submitted_at")]
        if ids:
            with self.connect(self.validator) as conn:
                for i in ids:
                    if conn.execute("select api.record_validation(%s, true, '{}')", (i,)).fetchone()[0] is None:
                        raise SystemExit(f"the record's validator cannot see change set {i} (a scope not granted to it)")
        return len(ids)

    def claim(self, subject: str, predicate: str = "http://www.w3.org/2000/01/rdf-schema#label") -> str:
        r = self.rows("select id from kernel.claim where subject = %s and predicate = %s order by recorded_at desc limit 1",
                      (subject, predicate))
        if not r:
            raise SystemExit(f"no claim {subject} {predicate}")
        return str(r[0]["id"])

    # ------------------------------------------------------------------ the provider
    def service_once(self, provider: Path, env: dict | None = None, timeout: float = 120,
                     role: str | None = None, args: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
        """The provider's service (or, with `args`, its command), one pass, as its own role through a login of its
        own; then validate what it submitted."""
        provider = Path(provider)
        role = role or meta(provider).get("role")
        if not role:
            raise SystemExit(f"{provider}: provider.yaml names no `role:`")
        r = self.rows("select rolsuper, pg_has_role(oid, 'kk_agent', 'member') agent, "
                      "array(select e from unnest(array['kk_owner', 'kk_validator', 'kk_reviewer', 'kk_steward']) e "
                      "      where pg_has_role(r.oid, e, 'member')) elevated from pg_roles r where rolname = %s", (role,))
        if not r or r[0]["rolsuper"] or not r[0]["agent"] or r[0]["elevated"]:
            raise SystemExit(f"{provider}: role {role!r} refused: it must exist and be an agent (kk_agent), and be neither "
                             f"a superuser nor hold an elevated role ({r[0]['elevated'] if r else 'no such role'})")
        pythonpath = os.pathsep.join(p for p in (str(KERNEL / "src"), str(provider), os.environ.get("PYTHONPATH")) if p)
        out = subprocess.run([sys.executable, "-m", package(provider), *args], cwd=provider, capture_output=True, text=True,
                             timeout=timeout,
                             env={k: v for k, v in os.environ.items() if not k.startswith("PG")}
                             | {"DATABASE_URL": self.login(role), "KK_ROLE": role, "KK_ONCE": "1",
                                "PYTHONPATH": pythonpath, **(env or {})})
        if out.returncode:   # no case counts on a run that did not finish
            raise SystemExit(f"{provider.name}: its service exited {out.returncode}\n{out.stdout[-2000:]}\n{out.stderr[-2000:]}")
        self.validate()
        return out

    def agent_of(self, provider: Path) -> str:
        role = meta(provider).get("role")
        r = self.rows("select iri from kernel.agent where db_role = %s", (role,))
        if not r:
            raise SystemExit(f"{provider}: no agent for role {role}")
        return r[0]["iri"]

    # ------------------------------------------------------------------ reads
    def rows(self, statement: str, args=(), role: str | None = None) -> list[dict]:
        conn = self.connect(role) if role else self.su
        try:
            with conn.cursor() as cur:
                cur.execute(statement, args)
                cols = [d.name for d in cur.description or []]
                return [dict(zip(cols, r)) for r in cur.fetchall()] if cols else []
        finally:
            if role:
                conn.close()

    def applied_by(self, agent: str, after: str = "-infinity") -> list[dict]:
        """The change sets `agent` had applied since `after` (a timestamp), oldest first."""
        return self.rows("select id, target_scope, ops, status from kernel.change_set where attributed_to = %s "
                         "and status = 'applied' and submitted_at > %s::timestamptz order by submitted_at", (agent, after))

    def now(self) -> str:
        return str(self.rows("select clock_timestamp() t")[0]["t"])

    def drop(self) -> None:
        self.su.close()
        subprocess.run(["dropdb", "--if-exists", "--force", self.db], check=True, capture_output=True)
        for name in [*self.passwords, *reversed(self.made)]:
            subprocess.run(["psql", "-d", "postgres", "-qAtc", f'drop role if exists "{name}"'], capture_output=True)


def dump(x) -> str:
    return json.dumps(x, default=str, sort_keys=True)
