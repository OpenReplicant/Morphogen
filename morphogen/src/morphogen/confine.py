"""Running code that was not reviewed (a model-written candidate, an agent harness) as an OS user of its
own (R5-24).

The OS user is KK_RUN_AS: a user with no rights of its own (no login shell, no home, in no group with
files of ours). The process that starts such code (the sandbox, the reconciler, the builder) must be able
to switch to it: root, or CAP_SETUID and CAP_SETGID. What the confined code can then reach:

  files      only what is readable by any user: the repository, the Python it runs with, and the copy of
             its own code in a `workspace()`; its own `home()` is the one place it may write. This
             process's private directories (0700) and its /proc entries (root's) are closed to it.
  database   only the login it is given (morphogen.logins): `check_cluster` refuses to run anything
             while the cluster lets any login in without its password, as a cluster trusting local
             sockets would.
  processes  `kill_all` ends every process of the run user, whatever it started and however detached.

Nothing here runs without KK_RUN_AS: `run_user()` raises Unconfined, and callers refuse to run the code.
"""
from __future__ import annotations

import contextlib
import json
import os
import pwd
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


class Unconfined(RuntimeError):
    """Model-written code would run without an OS user of its own, or could reach past its login."""


def run_user() -> pwd.struct_passwd:
    name = os.environ.get("KK_RUN_AS")
    if not name:
        raise Unconfined("KK_RUN_AS is not set: model-written code runs only as an OS user of its own")
    try:
        u = pwd.getpwnam(name)
    except KeyError:
        raise Unconfined(f"KK_RUN_AS names no user: {name}") from None
    if u.pw_uid in (0, os.geteuid()):
        raise Unconfined(f"KK_RUN_AS ({name}) must be a user other than root and this process's own")
    return u


def popen(cmd: list[str], env: dict, **kw) -> subprocess.Popen:
    """Start cmd as the run user, in a session of its own, with exactly `env`."""
    u = run_user()
    return subprocess.Popen(cmd, env=env, user=u.pw_uid, group=u.pw_gid, extra_groups=[], umask=0o077,
                            start_new_session=True, **kw)


def run(cmd: list[str], env: dict, timeout: float | None = None, **kw) -> subprocess.CompletedProcess:
    """popen, waited for; on a timeout every process of the run user is ended."""
    with popen(cmd, env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kw) as p:
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_all()
            out, err = p.communicate()
        return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def kill_all() -> int:
    """End every process of the run user. Returns how many were signalled."""
    uid, n = run_user().pw_uid, 0
    for _ in range(20):                                  # again, for anything forked meanwhile
        found = []
        for proc in Path("/proc").iterdir():
            try:
                if proc.name.isdigit() and proc.stat().st_uid == uid \
                        and (proc / "stat").read_text().rsplit(")", 1)[1].split()[0] != "Z":   # a zombie is already dead
                    found.append(int(proc.name))
            except OSError:
                continue
        live = []
        for pid in found:
            try:
                os.kill(pid, signal.SIGKILL)
                live.append(pid)
            except OSError:
                pass
        if not live:
            return n
        n += len(live)
        time.sleep(0.05)
    raise Unconfined("the run user's processes keep coming back")


@contextlib.contextmanager
def workspace(prefix: str = "kk-ws-"):
    """A directory the run user may read but not write: copy code here to run it confined."""
    d = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        d.chmod(0o755)
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def readable(d: Path) -> None:
    """Make a copied tree readable by the run user (directories 0755, files 0644)."""
    for p in [d, *d.rglob("*")]:
        if not p.is_symlink():
            p.chmod(0o755 if p.is_dir() else 0o644)


@contextlib.contextmanager
def home(prefix: str = "kk-home-"):
    """A directory only the run user may write (HOME and TMPDIR for the confined code); removed after,
    once every process of the run user has ended."""
    u = run_user()
    d = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        os.chown(d, u.pw_uid, u.pw_gid)
        d.chmod(0o700)
        yield d
    finally:
        kill_all()
        shutil.rmtree(d, ignore_errors=True)


PROBE = """
import json, sys
import psycopg
open_to = []
for role in json.loads(sys.argv[1]):
    try:
        psycopg.connect(dbname="postgres", user=role, connect_timeout=5).close()
        open_to.append(role)
    except Exception:
        pass
print(json.dumps(open_to))
"""


def check_cluster(env: dict, roles: list[str]) -> None:
    """Refuse when the cluster, reached as the confined code would reach it (env: PGHOST, PGPORT), lets
    any of these login roles in without a password. Run as the run user, so peer auth answers for it."""
    probe = {k: v for k, v in env.items() if k in ("PATH", "LANG", "PGHOST", "PGPORT", "PGSSLMODE")}
    with home() as h:
        probe.update(HOME=str(h), TMPDIR=str(h), PGPASSFILE=os.devnull, PGSERVICEFILE=os.devnull)
        out = run([sys.executable, "-I", "-c", PROBE, json.dumps(sorted(roles))], probe, timeout=60, cwd=h)
    if out.returncode:
        raise Unconfined(f"the cluster probe failed as {run_user().pw_name}: {(out.stderr or '').strip()[-300:]}")
    open_to = json.loads(out.stdout or "[]")
    if open_to:
        raise Unconfined(f"the cluster lets {', '.join(open_to)} in without a password: confined code could act "
                         "as any of them (use scram-sha-256 or md5 in pg_hba.conf, not trust)")


def login_roles(conn) -> list[str]:
    return [r[0] for r in conn.execute("select rolname from pg_roles where rolcanlogin").fetchall()]
