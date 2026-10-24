"""Running code that was not reviewed (a model-written candidate, an agent harness) as an OS user of its
own (R5-24).

KK_RUN_AS names a pool of OS users (comma-separated), each with no rights of its own: no login shell, no
home, in no group with files of ours, and a uid nothing else on the host runs as (a container's processes
included: `useradd --system` can hand out 999, the uid of Postgres in its image). Each run leases one
user for itself (`lease()`, a lock only root can take), so two confined runs never share a user: they cannot read each other's environment, trace
each other or end each other's processes. The process that starts confined code (the sandbox, the
reconciler, the builder) must be able to switch users: root, or CAP_SETUID and CAP_SETGID.

What a confined run can reach:
  files      what any user may read (the repository, the Python it runs with), the copy of its own code
             made by `copy_tree` (regular files and directories only, fixed modes) in a `workspace()`, and
             its `home()`, the one place it writes. Private directories (0700) and root's /proc entries
             are closed to it.
  database   only the login it is given: `check_cluster` refuses while the cluster's pg_hba trusts any
             connection, or a probe run as the leased user reaches any login role without a password
             over the address the code gets (and 127.0.0.1, ::1). It does not see a password the operator
             left readable (never write one in the repository).
  processes  at most RLIMIT_NPROC of them, no core files, files up to RLIMIT_FSIZE; `Lease.kill_all`
             ends every process whose real uid is the leased user (kill(-1) from a process running as
             it, so setuid children too), until none is left.
  network    only the addresses its lease allows (`lease(allow=...)`: the record's address, the telemetry
             endpoint, a model API the operator names), by an nftables chain of the leased user's own
             (table inet kk_confine, matched on the socket's uid); anything else is rejected, loopback
             included, and with no lease the chain rejects everything. Names are resolved when the lease
             starts and the code gets no DNS: give it addresses, or names /etc/hosts answers. Unix sockets
             are files, not network (a Postgres socket directory stays reachable; the Docker socket is
             closed by its mode).
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import pwd
import resource
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psycopg


class Unconfined(RuntimeError):
    """Model-written code would run without an OS user of its own, or could reach past its login."""


LOCKS = Path(os.environ.get("KK_RUN_LOCKS", "/run/lock/kk-confine"))
LIMITS = {resource.RLIMIT_NPROC: 512, resource.RLIMIT_CORE: 0, resource.RLIMIT_FSIZE: 1 << 30}


def pool() -> list[pwd.struct_passwd]:
    names = [x.strip() for x in os.environ.get("KK_RUN_AS", "").split(",") if x.strip()]
    if not names:
        raise Unconfined("KK_RUN_AS is not set: model-written code runs only as an OS user of its own")
    users = []
    for name in names:
        try:
            u = pwd.getpwnam(name)
        except KeyError:
            raise Unconfined(f"KK_RUN_AS names no user: {name}") from None
        if u.pw_uid in (0, os.geteuid()):
            raise Unconfined(f"KK_RUN_AS ({name}) must be a user other than root and this process's own")
        users.append(u)
    return users


def _limits() -> None:
    for k, v in LIMITS.items():
        resource.setrlimit(k, (v, v))


class Lease:
    """One leased run user: start code as it, end all of it."""

    def __init__(self, user: pwd.struct_passwd):
        self.user = user

    @property
    def name(self) -> str:
        return self.user.pw_name

    def popen(self, cmd: list[str], env: dict, **kw) -> subprocess.Popen:
        """Start cmd as the leased user, in a session of its own, with exactly `env`, under LIMITS."""
        return subprocess.Popen(cmd, env=env, user=self.user.pw_uid, group=self.user.pw_gid, extra_groups=[],
                                umask=0o077, start_new_session=True, preexec_fn=_limits, **kw)

    def run(self, cmd: list[str], env: dict, timeout: float | None = None, **kw) -> subprocess.CompletedProcess:
        """popen, waited for; on a timeout every process of the leased user is ended."""
        with self.popen(cmd, env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kw) as p:
            try:
                out, err = p.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.kill_all()
                out, err = p.communicate()
            return subprocess.CompletedProcess(cmd, p.returncode, out, err)

    def live(self) -> list[int]:
        """Processes whose real uid is the leased user (setuid ones too), zombies aside."""
        out = []
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                status = dict(line.split(":", 1) for line in (proc / "status").read_text().splitlines() if ":" in line)
            except OSError:
                continue
            if int(status["Uid"].split()[0]) == self.user.pw_uid and not status["State"].strip().startswith("Z"):
                out.append(int(proc.name))
        return out

    def kill_all(self) -> None:
        """End every process whose real uid is the leased user: kill(-1, SIGKILL) from a process running as
        it (which reaches exactly those, with no pid to reuse), again until none is left."""
        for _ in range(100):
            if not self.live():
                return
            subprocess.run([sys.executable, "-I", "-c", "import os, signal; os.kill(-1, signal.SIGKILL)"],
                           user=self.user.pw_uid, group=self.user.pw_gid, extra_groups=[], env={"PATH": "/usr/bin:/bin"},
                           cwd="/", capture_output=True)
            time.sleep(0.02)
        raise Unconfined(f"the processes of {self.name} keep coming back")

    @contextlib.contextmanager
    def home(self, prefix: str = "kk-home-"):
        """A directory only the leased user may write (HOME and TMPDIR for the confined code); removed
        after, once every process of the user has ended."""
        d = Path(tempfile.mkdtemp(prefix=prefix))
        try:
            os.chown(d, self.user.pw_uid, self.user.pw_gid)
            d.chmod(0o700)
            yield d
        finally:
            self.kill_all()
            shutil.rmtree(d, ignore_errors=True)

    def take_back(self, d: Path) -> None:
        """End the user's processes, then make everything under d root's and closed to it: what it wrote
        cannot change while it is checked and copied."""
        self.kill_all()
        for p in [d, *d.rglob("*")]:
            os.chown(p, 0, 0, follow_symlinks=False)
            if not p.is_symlink():
                p.chmod(0o700 if p.is_dir() or p.stat().st_mode & 0o111 else 0o600)


TABLE = "kk_confine"


def _nft(script: str) -> None:
    try:
        out = subprocess.run(["nft", "-f", "-"], input=script, capture_output=True, text=True)
    except FileNotFoundError:
        raise Unconfined("nft is not installed: a confined run's network cannot be limited (install nftables)") from None
    if out.returncode:
        raise Unconfined(f"nft refused the run user's chain: {out.stderr.strip()[-300:]}")


def addresses(allow) -> list[tuple[str, int]]:
    """(address, port) for each (host, port) allowed; a socket directory (a path) needs no address."""
    out = set()
    for host, port in allow:
        host = str(host).strip("[]")
        if not host or host.startswith("/"):
            continue
        try:
            infos = socket.getaddrinfo(host, int(port), type=socket.SOCK_STREAM)
        except (socket.gaierror, ValueError) as e:
            raise Unconfined(f"cannot allow {host}:{port} to a confined run: {e}") from None
        out |= {(i[4][0], int(port)) for i in infos}
    return sorted(out)


def fence(user: pwd.struct_passwd, allow=()) -> list[tuple[str, int]]:
    """Set the user's chain: TCP to the allowed addresses, nothing else (no allow: nothing at all)."""
    uid, chain = user.pw_uid, f"u{user.pw_uid}"
    got = addresses(allow)
    rules = "".join(f"add rule inet {TABLE} {chain} {'ip6' if ':' in a else 'ip'} daddr {a} tcp dport {p} accept\n"
                    for a, p in got)
    listed = subprocess.run(["nft", "list", "chain", "inet", TABLE, "out"], capture_output=True, text=True).stdout
    jump = "" if f'comment "{chain}"' in listed else f'add rule inet {TABLE} out meta skuid {uid} jump {chain} comment "{chain}"\n'
    _nft(f"add table inet {TABLE}\n"
         f"add chain inet {TABLE} out {{ type filter hook output priority 0 ; policy accept ; }}\n"
         f"add chain inet {TABLE} {chain}\nflush chain inet {TABLE} {chain}\n{jump}{rules}"
         f"add rule inet {TABLE} {chain} meta l4proto tcp reject with tcp reset\n"
         f"add rule inet {TABLE} {chain} reject\n")
    return got


@contextlib.contextmanager
def lease(allow=()):
    """A run user nobody else holds, for the life of the context, reaching only the (host, port) pairs in
    `allow` over the network. A user that already has processes is refused, not cleared: they may be
    another program's that shares its uid."""
    LOCKS.mkdir(mode=0o700, parents=True, exist_ok=True)
    if LOCKS.stat().st_uid != os.geteuid() or LOCKS.stat().st_mode & 0o077:
        raise Unconfined(f"{LOCKS} must be this process's own and closed to others")
    for u in pool():
        f = open(LOCKS / f"{u.pw_name}.lock", "w")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            f.close()
            continue
        got = Lease(u)
        if busy := got.live():
            f.close()
            raise Unconfined(f"run user {u.pw_name} (uid {u.pw_uid}) already has processes {busy[:5]}: its uid may "
                             "belong to something else on this host (end them, or give it a uid of its own)")
        try:
            fence(u, allow)
            yield got
        finally:
            try:
                got.kill_all()
                fence(u)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
            f.close()
        return
    raise Unconfined(f"every run user in KK_RUN_AS is in use ({len(pool())})")


@contextlib.contextmanager
def workspace(prefix: str = "kk-ws-"):
    """A directory run users may read but not write: copy code here (copy_tree) to run it confined."""
    d = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        d.chmod(0o755)
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def copy_tree(src: Path, dst: Path, skip: tuple[str, ...] = ("__pycache__",)) -> None:
    """Copy src to dst as new root-owned files: directories 0755, files 0644 (0755 when the source has any
    execute bit). Only regular files and directories, each with one link; anything else (a symbolic or
    hard link, a device, a fifo, a socket) is refused. No source mode, owner or setuid bit is carried."""
    def copy(s: Path, d: Path) -> None:
        st = os.lstat(s)
        if stat.S_ISDIR(st.st_mode):
            os.mkdir(d, 0o755)
            os.chmod(d, 0o755)
            for name in sorted(os.listdir(s)):
                if name not in skip:
                    copy(s / name, d / name)
        elif stat.S_ISREG(st.st_mode) and st.st_nlink == 1:
            fd = os.open(s, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                if os.fstat(fd).st_ino != st.st_ino:
                    raise ValueError(f"{s} changed while it was copied")
                with os.fdopen(os.dup(fd), "rb") as r, open(d, "xb") as w:
                    shutil.copyfileobj(r, w)
            finally:
                os.close(fd)
            os.chmod(d, 0o755 if st.st_mode & 0o111 else 0o644)
        else:
            raise ValueError(f"{s} is not a regular file or directory with one link")
    copy(src, dst)


PROBE = """
import json, sys
import psycopg
args = json.loads(sys.argv[1])
found, errors = [], []
for host, required in args["hosts"]:
    for db in args["databases"]:
        for role in args["roles"]:
            try:
                psycopg.connect(host=host, port=args["port"], dbname=db, user=role, connect_timeout=5).close()
                found.append(f"{role}@{db} via {host}")
            except psycopg.OperationalError as e:
                text = str(e)
                if "password" in text or "no pg_hba.conf entry" in text or "does not exist" in text:
                    continue            # asked for a password, or no rule lets it in, or no such database/role
                if required:
                    errors.append(f"{host}: {text.strip()[:200]}")
print(json.dumps({"found": found, "errors": errors}))
"""


def check_cluster(su, run: Lease, host: str, port: str, reach: bool = True) -> None:
    """Refuse unless the cluster asks every connection for a password. `su`: a connection to the cluster (a
    superuser's, to read pg_hba_file_rules; otherwise only the probe decides); host, port: where the
    confined code connects (a socket directory or a host name); reach=False when its lease does not allow
    that address (then not reaching it is the expected answer)."""
    try:
        bad = su.execute("""select line_number, type, database, user_name, auth_method, error from pg_hba_file_rules
                            where error is not null or auth_method in ('trust', 'ident', 'peer')""").fetchall()
    except psycopg.errors.InsufficientPrivilege:          # not a superuser: the probe below decides alone
        su.rollback() if not su.autocommit else None
        bad = []
    for line, kind, dbs, users, method, error in bad:
        if error:
            raise Unconfined(f"pg_hba.conf line {line}: {error}")
        if method == "trust":
            raise Unconfined(f"pg_hba.conf line {line} trusts {kind} connections ({users} to {dbs}): confined code "
                             "could act as any role (use scram-sha-256)")
        if run.name in (users or []) or "all" in (users or []):
            maps = su.execute("select system_user from pg_ident_file_mappings").fetchall()
            if method != "peer" or any(m[0] in (run.name, "all") or m[0].startswith("/") for m in maps):
                raise Unconfined(f"pg_hba.conf line {line} ({method}) could let {run.name} in as a database role")
    roles = [r[0] for r in su.execute("select rolname from pg_roles where rolcanlogin").fetchall()]
    dbs = [r[0] for r in su.execute("select datname from pg_database where datallowconn").fetchall()]
    hosts = [(host, reach)] + [(h, False) for h in ("127.0.0.1", "::1") if h != host]
    with run.home() as h:
        env = {"PATH": "/usr/bin:/bin", "HOME": str(h), "PGPASSFILE": os.devnull, "PGSERVICEFILE": os.devnull}
        out = run.run([sys.executable, "-I", "-c", PROBE,
                       json.dumps({"hosts": hosts, "port": port, "databases": dbs, "roles": roles})], env, timeout=300, cwd=h)
    if out.returncode:
        raise Unconfined(f"the cluster probe failed as {run.name}: {(out.stderr or '').strip()[-300:]}")
    got = json.loads(out.stdout)
    if got["errors"]:
        raise Unconfined(f"the cluster probe could not reach {host}:{port} as {run.name}: {got['errors'][0]}")
    if got["found"]:
        raise Unconfined(f"the cluster lets {run.name} in without a password: {', '.join(got['found'][:5])}")


def endpoint(url: str) -> tuple[str, str] | None:
    """(host, port) of an http(s) URL, or None."""
    from urllib.parse import urlsplit
    u = urlsplit(url or "")
    if u.scheme not in ("http", "https") or not u.hostname:
        return None
    return u.hostname, str(u.port or (443 if u.scheme == "https" else 80))


def where(conninfo: str = "") -> tuple[str, str]:
    """(host, port) a conninfo (or the PG* environment) points at."""
    from psycopg.conninfo import conninfo_to_dict
    d = conninfo_to_dict(conninfo) if conninfo else {}
    return (str(d.get("host") or os.environ.get("PGHOST") or "/var/run/postgresql"),
            str(d.get("port") or os.environ.get("PGPORT") or "5432"))
