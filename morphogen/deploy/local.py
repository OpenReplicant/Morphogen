"""Morphogen on a machine of your own (T23): one command brings up the record, the services, the compose runner and
the UI; others add a person, give an agent (Claude Code) its own login, record a conversation and propose a
described system.

  python3 morphogen/deploy/local.py up                 Postgres in Docker, install, the services, the UI
  python3 morphogen/deploy/local.py person NAME        a person who signs in to the UI and reviews (asks the password)
  python3 morphogen/deploy/local.py agent NAME         an agent's own login, and an MCP config for Claude Code
  python3 morphogen/deploy/local.py record FILE --source NAME   a conversation (JSON lines) as notes, for an interview
  python3 morphogen/deploy/local.py propose SYSTEM     a described system's compose file, to review in the UI
  python3 morphogen/deploy/local.py claude NAME        Claude Code as the agent NAME, its MCP config given
  python3 morphogen/deploy/local.py status             what runs, and where
  python3 morphogen/deploy/local.py down [--db]        stop the services (and Postgres, with --db)

`up --foreground` stays in the foreground, stops everything on SIGTERM and exits when a process it started does
(the container image's supervisor, T24). Settings by environment: MORPHOGEN_DB=embedded runs Postgres from this
machine's own binaries (initdb, pg_ctl) in MORPHOGEN_PGDATA (default MORPHOGEN_HOME/pgdata) instead of in Docker;
MORPHOGEN_COMPOSE=external leaves the compose runner to someone else (the image runs it as the one process that
holds the container socket); MORPHOGEN_RUNTIME=quadlet runs managed systems as Podman Quadlet units (runtime-quadlet:
Podman 5.6 or later and systemd on this machine, a user session when not root) instead of Docker Compose; MORPHOGEN_UI_HOST (default 127.0.0.1) is where the UI listens;
MORPHOGEN_OPERATOR_NAME and MORPHOGEN_OPERATOR_EMAIL name who brought the instance up, when git does not.

Everything it keeps is in MORPHOGEN_HOME (default ~/.local/state/morphogen), readable by you alone:
  secrets.json   the database superuser's password, the services' and the UI's logins, the UI's token secret,
                 the telemetry secret; generated once, never printed, never in the repository
  intent/        Morphogen's intent, a git repository of its own (copied from morphogen/intent on the first up):
                 the intent actuator commits approved changes here, the reconcilers run what is committed
  artifacts/     source files the encoders stored (conversations), which the quote verifier reads
  logs/          one log per process; pids.json, the processes `up` started
  mcp/           per agent, the MCP config `agent` wrote

The record is Postgres 16 in the container `morphogen-postgres` (image pinned by digest), published on
127.0.0.1 only, asking every login for its password (scram-sha-256), data in the volume `morphogen-pgdata`.
Every service, and `record` and `propose`, connects as a login of its own that may switch to its provider's role
only, with a password derived for that login alone; the reconciler holds the secret they are derived from, and no
service does. The UI connects as kk_authenticator, which may act as any signed-in person (and any provider): it is
the one process trusted that far. The superuser's password is used to install, and to add people and agents.

What this does not protect against: every process runs as you, so a service could read MORPHOGEN_HOME. The
separation above stops a mistaken service, not a hostile one; model-written code, which is not trusted, is never
started here.

Needs: Docker, git, psql (the Postgres client), Python 3.12+ with the requirements in docs/DEVELOPING.md, and
gitleaks 8.30.1 on PATH for the design agent's intake filter. Model-written code (the builder and the sandbox) is
not started here: it needs run users and nftables (docs/DEVELOPING.md, section 1).
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "src")]
HOME = Path(os.environ.get("MORPHOGEN_HOME", Path.home() / ".local" / "state" / "morphogen"))
EMBEDDED = os.environ.get("MORPHOGEN_DB") == "embedded"
PGDATA = Path(os.environ.get("MORPHOGEN_PGDATA", HOME / "pgdata"))
COMPOSE = os.environ.get("MORPHOGEN_COMPOSE") != "external"
RUNTIME = os.environ.get("MORPHOGEN_RUNTIME", "compose")       # the runtime slot's provider: runtime-compose or runtime-quadlet
DB = "morphogen"
IMAGE = "postgres:16.9@sha256:ddfe3e8713e3ee5b8f286082cb12512488dfbf3f5a1ecb0b74a42e6055af0a5f"
ENV = "local"
# The services the reconciler runs from intent (environments/local/<provider>.yaml): directory, module, settings,
# and the role each acts as. Every one gets a login of its own that may switch to that role only (`logins`).
SERVICES = {
    "validator-shacl": ("kernel/providers/validator-shacl", "validator", {}, "kkm_validator"),
    "belief-corroboration": ("kernel/providers/belief-corroboration", "belief_corroboration", {}, "kkm_belief"),
    "truth-maintenance": ("kernel/providers/truth-maintenance", "truth_maintenance", {}, "kkm_truth_maintenance"),
    "verifier-quotes": ("kernel/providers/verifier-quotes", "verifier_quotes", {"KK_ARTIFACTS": "{artifacts}"}, "kkm_verifier_quotes"),
    "recall-bm25": ("kernel/providers/recall-bm25", "recall_bm25", {}, "kkm_recall_index"),
    "anomaly": ("morphogen/modules/anomaly", "anomaly", {}, "kkm_anomaly"),
    "planner": ("morphogen/modules/planner", "planner", {"KK_INTENT_DIR": "{intent}", "KK_INTENT_ENV": ENV}, "kkm_planner"),
    "intent-actuator": ("morphogen/modules/intent-actuator", "intent_actuator", {"KK_INTENT_DIR": "{intent}", "KK_INTENT_ENV": ENV},
                        "kkm_intent_actuator"),
    "prediction-verifier": ("morphogen/modules/prediction-verifier", "prediction_verifier", {}, "kkm_prediction_verifier"),
    "gaps-shacl": ("kernel/providers/gaps-shacl", "gaps_shacl", {}, "kkm_gaps_shacl"),
}
# Started by local.py itself, each as its own login too.
OTHERS = {"observer-otel": ("morphogen/modules/observer-otel", "kkm_observer_otel"),
          "interview-encoder": ("morphogen/modules/interview-encoder", "kkm_interview_encoder"),
          "design-blueprint": ("morphogen/modules/design-blueprint", "kkm_design_blueprint"),
          "runtime-compose": ("morphogen/modules/runtime-compose", "kkm_runtime_compose"),
          "runtime-quadlet": ("morphogen/modules/runtime-quadlet", "kkm_runtime_quadlet")}
NEEDS = ["psycopg", "yaml", "pyshacl", "rdflib", "mcp", "jwt", "starlette", "uvicorn"]


def say(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str) -> None:
    raise SystemExit(f"morphogen: {msg}")


# ------------------------------------------------------------------ state
def secret() -> dict:
    """The instance's secrets and settings, generated once (any missing key is filled in). MORPHOGEN_HOME is made
    yours alone on every call, and a secrets file another user could read is refused."""
    HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
    if HOME.stat().st_uid != os.getuid():
        die(f"{HOME} belongs to another user")
    HOME.chmod(0o700)
    f = HOME / "secrets.json"
    s = json.loads(f.read_text()) if f.exists() else {}
    if f.exists() and f.stat().st_mode & 0o077:
        die(f"{f} is readable by others: chmod 600 it, or start again with a new MORPHOGEN_HOME")
    want = {**{k: secrets.token_urlsafe(32) for k in ("superuser", "logins", "authenticator", "jwt", "otlp")},
            "instance": "morphogen",          # names the container (<instance>-postgres) and volume (<instance>-pgdata)
            "db_port": 55432, "ui_port": 8470, "otlp_port": 54318}
    if set(want) - set(s):
        s = {**want, **s}
        f.touch(mode=0o600)
        f.chmod(0o600)
        f.write_text(json.dumps(s, indent=2) + "\n")
    return s


def conninfo(s: dict, user: str = "postgres", password: str | None = None, db: str = DB) -> str:
    from psycopg.conninfo import make_conninfo
    return make_conninfo(host="127.0.0.1", port=s["db_port"], dbname=db, user=user,
                         password=password if password is not None else s["superuser"])


def container(s: dict) -> str:
    return f"{s.get('instance', 'morphogen')}-postgres"


def volume(s: dict) -> str:
    return f"{s.get('instance', 'morphogen')}-pgdata"


def pg_env(s: dict) -> dict:
    """The PG* environment install.py and people.py use (a superuser, like psql)."""
    return {"PGHOST": "127.0.0.1", "PGPORT": str(s["db_port"]), "PGUSER": "postgres", "PGPASSWORD": s["superuser"]}


def pids() -> dict:
    f = HOME / "pids.json"
    got = json.loads(f.read_text()) if f.exists() else {}
    return {k: v for k, v in got.items() if isinstance(v, dict)}


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


# ------------------------------------------------------------------ checks
def preflight() -> None:
    if sys.version_info < (3, 12):
        die(f"Python 3.12 or newer is needed (this is {sys.version.split()[0]})")
    if RUNTIME not in ("compose", "quadlet"):
        die(f"MORPHOGEN_RUNTIME: compose or quadlet, not {RUNTIME!r}")
    quadlet = COMPOSE and RUNTIME == "quadlet"
    docker = (COMPOSE and not quadlet) or not EMBEDDED
    want = ["git", "psql", *(["docker"] if docker else []), *(["initdb", "pg_ctl"] if EMBEDDED else []),
            *(["podman", "systemctl"] if quadlet else [])]
    missing = [t for t in want if not shutil.which(t)]
    if missing:
        die(f"not on PATH: {', '.join(missing)} (docs/DEVELOPING.md, section 1)")
    if docker and subprocess.run(["docker", "info"], capture_output=True).returncode:
        die("Docker does not answer: start it first")
    if quadlet and subprocess.run(["podman", "quadlet", "--help"], capture_output=True).returncode:
        die("this Podman has no quadlet commands: runtime-quadlet needs Podman 5.6 or later")
    import importlib.util
    lost = [m for m in NEEDS if importlib.util.find_spec(m) is None]
    if lost:
        die(f"Python packages missing ({', '.join(lost)}): pip install -r kernel/contract/requirements.txt "
            "-r kernel/providers/kernel-mcp/requirements.txt -r morphogen/modules/observer-otel/requirements.txt "
            "-r morphogen/modules/registry-lookup/requirements.txt")
    if not shutil.which("gitleaks"):
        say("note: gitleaks is not on PATH; the design agent will refuse to propose until it is (the intake filter fails closed)")


# ------------------------------------------------------------------ Postgres
def postgres(s: dict) -> None:
    if EMBEDDED:
        return postgres_embedded(s)
    state = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", container(s)], capture_output=True, text=True)
    if state.returncode:
        say(f"starting Postgres ({IMAGE.split('@')[0]}) on 127.0.0.1:{s['db_port']}")
        pw = pw_file(s)
        subprocess.run(["docker", "run", "-d", "--name", container(s), "-p", f"127.0.0.1:{s['db_port']}:5432",
                        "-e", "POSTGRES_PASSWORD_FILE=/run/morphogen/pw", "-e", "POSTGRES_INITDB_ARGS=--auth=scram-sha-256",
                        "-e", "POSTGRES_HOST_AUTH_METHOD=scram-sha-256", "-v", f"{volume(s)}:/var/lib/postgresql/data",
                        "--mount", f"type=bind,src={pw},dst=/run/morphogen/pw,readonly", IMAGE],
                       check=True, capture_output=True)
    elif state.stdout.strip() != "true":
        pw_file(s)                    # Docker checks a bind mount's source at every start, not only the first
        subprocess.run(["docker", "start", container(s)], check=True, capture_output=True)
    answers(s)


def postgres_embedded(s: dict) -> None:
    """Postgres from this machine's binaries, as you: the data in PGDATA, listening on 127.0.0.1 and on a socket in
    MORPHOGEN_HOME/run (yours alone), asking every login for its password as the container does."""
    run, logs = HOME / "run", HOME / "logs"
    for d in (run, logs):
        d.mkdir(exist_ok=True, mode=0o700)
    if not (PGDATA / "PG_VERSION").exists():
        say(f"initialising Postgres in {PGDATA}")
        pw = pw_file(s, mode=0o600)
        try:
            out = subprocess.run(["initdb", "-D", str(PGDATA), "-U", "postgres", "--auth=scram-sha-256", f"--pwfile={pw}",
                                  "-E", "UTF8", "--locale=C.UTF-8"], capture_output=True, text=True)
        finally:
            pw.unlink(missing_ok=True)
        if out.returncode:
            die(f"initdb failed: {out.stderr.strip()[-400:]}")
    if subprocess.run(["pg_ctl", "-D", str(PGDATA), "status"], capture_output=True).returncode:
        out = subprocess.run(["pg_ctl", "-D", str(PGDATA), "-w", "-l", str(logs / "postgres.log"), "-o",
                              f"-c listen_addresses=127.0.0.1 -p {s['db_port']} -k {run}", "start"], capture_output=True, text=True)
        if out.returncode:
            die(f"Postgres did not start: {logs / 'postgres.log'}")
    answers(s)


def answers(s: dict) -> None:
    import psycopg
    try:
        for _ in range(60):
            try:
                with psycopg.connect(conninfo(s, db="postgres"), connect_timeout=3) as conn:
                    conn.execute("select 1")
                return
            except psycopg.OperationalError:
                time.sleep(1)
        die(f"Postgres did not answer on 127.0.0.1:{s['db_port']}: " + (str(HOME / "logs" / "postgres.log") if EMBEDDED else f"docker logs {container(s)}"))
    finally:
        (HOME / "pg-password").unlink(missing_ok=True)          # read at start only; secrets.json keeps it


def pw_file(s: dict, mode: int = 0o644) -> Path:
    """The superuser's password as a file the container reads at init (never an argument or a variable), there
    only while the container starts. Readable inside the container (its postgres user reads it); on this machine
    MORPHOGEN_HOME, yours alone, keeps other users out. initdb, run as you, gets it at 0600."""
    f = HOME / "pg-password"
    f.touch(mode=mode)
    f.chmod(mode)
    f.write_text(s["superuser"])
    return f


def install(s: dict) -> None:
    import psycopg
    from psycopg import sql
    with psycopg.connect(conninfo(s, db="postgres"), autocommit=True) as su:
        if su.execute("select 1 from pg_database where datname = %s", (DB,)).fetchone():
            return
    say("installing the record and Morphogen's modules (a minute)")
    os.environ.update(pg_env(s))
    sys.path.insert(0, str(ROOT / "morphogen" / "modules"))
    import install as morphogen_install   # morphogen/modules/install.py
    subprocess.run(["createdb", DB], check=True, env={**os.environ, **pg_env(s)})
    morphogen_install.install(DB, morphogen_install.modules())
    morphogen_install.kernel.install(DB, ["verifier-quotes", "recall-bm25"])   # services here; Morphogen's tests run without them
    with psycopg.connect(conninfo(s), autocommit=True) as su:
        verifier = su.pgconn.encrypt_password(s["authenticator"].encode(), b"kk_authenticator", b"scram-sha-256").decode()
        su.execute(sql.SQL("alter role kk_authenticator login password {}").format(sql.Literal(verifier)))
        su.execute(sql.SQL("grant connect on database {} to kk_authenticator").format(sql.Identifier(DB)))


def declared_login(cwd: str) -> str | None:
    from morphogen.logins import login_of
    found = login_of(ROOT / cwd)
    return found[1] if found else None


def logins(s: dict) -> dict:
    """Every service's own login: may switch only to its role (noinherit, granted that role alone), password
    derived from the logins secret for that login alone (morphogen.logins.password_for), so no service holds
    another's. A provider that declares a login (provider.yaml `login`) keeps it. Writes service-logins.json for
    the reconciler: {provider: [role, login]} for providers that declare none. Returns {name: (role, login)}."""
    import psycopg
    from psycopg import sql
    from morphogen.logins import password_for
    os.environ["KK_LOGIN_SECRET"] = s["logins"]
    every = {name: (role, declared_login(cwd) or f"{role}_login") for name, (cwd, _, _, role) in SERVICES.items()}
    every.update({name: (role, declared_login(cwd) or f"{role}_login") for name, (cwd, role) in OTHERS.items()})
    with psycopg.connect(conninfo(s), autocommit=True) as su:
        for role, login in every.values():
            if not su.execute("select 1 from pg_roles where rolname = %s", (role,)).fetchone():
                die(f"the role {role} is missing: its provider is not installed in {DB}")
            if not su.execute("select 1 from pg_roles where rolname = %s", (login,)).fetchone():
                su.execute(sql.SQL("create role {} login noinherit").format(sql.Identifier(login)))
            verifier = su.pgconn.encrypt_password(password_for(login).encode(), login.encode(), b"scram-sha-256").decode()
            su.execute(sql.SQL("alter role {} login noinherit password {}").format(sql.Identifier(login), sql.Literal(verifier)))
            su.execute(sql.SQL("grant {} to {}").format(sql.Identifier(role), sql.Identifier(login)))
            su.execute(sql.SQL("grant connect on database {} to {}").format(sql.Identifier(DB), sql.Identifier(login)))
    f = HOME / "service-logins.json"
    f.write_text(json.dumps({n: list(rl) for n, rl in every.items() if n in SERVICES and not declared_login(SERVICES[n][0])}, indent=2))
    f.chmod(0o600)
    os.environ.pop("KK_LOGIN_SECRET")
    return every


def runtime_env(s: dict, every: dict) -> dict:
    """What the runtime (runtime-compose, or runtime-quadlet with MORPHOGEN_RUNTIME=quadlet) needs beside its engine:
    its own login, which reads plan steps and people's decisions (it runs only a file an approved step names, T26),
    and its code."""
    name = f"runtime-{RUNTIME}"
    rt = ROOT / "morphogen" / "modules" / name
    return {"DATABASE_URL": own(s, every, name), "KK_ROLE": OTHERS[name][1],
            "PYTHONPATH": os.pathsep.join([str(rt), str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "src")])}


def runtime_login(a) -> None:
    """Print the runtime's environment (JSON) for the process that holds the container socket (container.py), which
    must not read MORPHOGEN_HOME itself."""
    s = secret()
    print(json.dumps(runtime_env(s, logins(s))))


def own(s: dict, every: dict, name: str) -> str:
    """The conninfo of `name`'s own login."""
    from morphogen.logins import password_for
    os.environ["KK_LOGIN_SECRET"] = s["logins"]
    try:
        return conninfo(s, user=every[name][1], password=password_for(every[name][1]))
    finally:
        os.environ.pop("KK_LOGIN_SECRET")


# ------------------------------------------------------------------ intent
def operator() -> tuple[str, str]:
    """Who runs `up`: MORPHOGEN_OPERATOR_NAME/EMAIL, else their own git identity, else their login name here."""
    import getpass
    import socket
    get = lambda k: subprocess.run(["git", "config", "--get", k], capture_output=True, text=True).stdout.strip()  # noqa: E731
    user = getpass.getuser()
    return (os.environ.get("MORPHOGEN_OPERATOR_NAME") or get("user.name") or user,
            os.environ.get("MORPHOGEN_OPERATOR_EMAIL") or get("user.email") or f"{user}@{socket.gethostname()}")


def git(repo: Path, *args: str) -> str:
    name, email = operator()
    return subprocess.run(["git", "-C", str(repo), "-c", f"user.name={name}", "-c", f"user.email={email}", *args],
                          check=True, capture_output=True, text=True).stdout


def upgrade(d: Path) -> None:
    """Bring an intent repository made by an earlier `up` to what this one runs: since R5-48 the local environment runs
    the kernel's gap finder (gaps-shacl) where it ran map-gaps, and design-blueprint waits on its gaps. The change is
    committed as a bootstrap, like the first `up`'s, by the person running `up`."""
    local = d / "environments" / ENV
    old, new = local / "map-gaps.yaml", local / "gaps-shacl.yaml"
    if not old.exists() or new.exists():
        return
    cwd, module, env, _ = SERVICES["gaps-shacl"]
    lines = ["# Written by morphogen/deploy/local.py, upgrading an intent repository an earlier `up` made (R5-48: the kernel's",
             "# gap finder replaces map-gaps). A bootstrap, not reviewed; after it, changes come from approved plans.",
             "provider: gaps-shacl", f"service: python3 -m {module}", f"cwd: {cwd}", "env:", '  KK_SWEEP_SECONDS: "10"']
    new.write_text("\n".join(lines) + "\n")
    git(d, "rm", "-q", str(old.relative_to(d)))
    git(d, "add", str(new.relative_to(d)))
    git(d, "commit", "-qm", "bootstrap: the kernel's gap finder replaces map-gaps (R5-48)\n\nWritten by morphogen/deploy/local.py "
        "for the person running `up`; not a reviewed plan.")
    say("upgraded the intent repository: the kernel's gap finder (gaps-shacl) replaces map-gaps")


def intent() -> Path:
    d = HOME / "intent"
    if (d / ".git").exists():
        upgrade(d)
        return d
    say(f"making Morphogen's intent repository in {d}")
    shutil.copytree(ROOT / "morphogen" / "intent", d, ignore=shutil.ignore_patterns("experiments"))
    (d / "experiments").mkdir(exist_ok=True)
    (d / "experiments" / ".keep").write_text("")
    for env_dir in (d / "environments").iterdir():
        if env_dir.is_dir():
            shutil.rmtree(env_dir)
    for f in (d / "systems").glob("*"):     # the example systems (podinfo) are not yours to run
        shutil.rmtree(f) if f.is_dir() else f.unlink()
    (d / "systems" / ".keep").parent.mkdir(exist_ok=True)
    (d / "systems" / ".keep").write_text("")
    local = d / "environments" / ENV
    local.mkdir(parents=True)
    fill = {"intent": str(d), "artifacts": str(HOME / "artifacts")}
    for name, (cwd, module, env, _) in SERVICES.items():
        settings = {k: v.format(**fill) for k, v in env.items()}
        lines = ["# Written by morphogen/deploy/local.py at the first `up`, as the person who ran it (a bootstrap: not",
                 "# reviewed). After that, changes come from approved plans, committed by the intent actuator.",
                 f"provider: {name}", f"service: python3 -m {module}", f"cwd: {cwd}", "env:"]
        lines += [f"  {k}: {json.dumps(v)}" for k, v in {"KK_SWEEP_SECONDS": "10", **settings}.items()]
        (local / f"{name}.yaml").write_text("\n".join(lines) + "\n")
    git(d, "init", "-q")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "bootstrap: the local environment\n\nWritten by morphogen/deploy/local.py for the person running "
        "`up`; not a reviewed plan.")
    return d


# ------------------------------------------------------------------ processes
def started_at(pid: int) -> str:
    """When the process started, as `ps` says: with the pid, it names one process (a pid alone may be reused)."""
    return subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()


def start(name: str, argv: list[str], env: dict, cwd: Path = ROOT) -> dict:
    (HOME / "logs").mkdir(exist_ok=True, mode=0o700)
    log = open(HOME / "logs" / f"{name}.log", "a")
    p = subprocess.Popen(argv, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    return {"pid": p.pid, "started": started_at(p.pid)}


def ours(entry: dict) -> bool:
    return alive(entry["pid"]) and started_at(entry["pid"]) == entry["started"]


def up(a) -> None:
    preflight()
    s = secret()
    postgres(s)
    install(s)
    every = logins(s)
    repo = intent()
    (HOME / "artifacts").mkdir(exist_ok=True, mode=0o700)
    running = {k: v for k, v in pids().items() if ours(v)}
    if running:
        say(f"already running: {', '.join(sorted(running))} (`down` first to restart)")
        return
    path = os.pathsep.join([str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "src")])
    base = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR")}
    auth = conninfo(s, user="kk_authenticator", password=s["authenticator"])     # the UI's: it acts as signed-in people
    bare = f"host=127.0.0.1 port={s['db_port']} dbname={DB}"                       # the reconciler adds each service's own login
    otlp = f"http://127.0.0.1:{s['otlp_port']}"
    started = {
        "reconcile": start("reconcile", [sys.executable, str(ROOT / "morphogen" / "deploy" / "reconcile.py"), "--intent", str(repo),
                                         "--env", ENV, "--repo", str(ROOT)],
                           {**base, "DATABASE_URL": bare, "KK_LOGIN_SECRET": s["logins"], "KK_SERVICE_LOGINS": str(HOME / "service-logins.json"),
                            "PYTHONPATH": path, "OTEL_EXPORTER_OTLP_ENDPOINT": otlp, "KK_OTLP_SECRET": s["otlp"]}),
        "observer-otel": start("observer-otel", [sys.executable, "-m", "observer_otel"],
                               {**base, "DATABASE_URL": own(s, every, "observer-otel"), "KK_ROLE": "kkm_observer_otel",
                                "PYTHONPATH": os.pathsep.join([str(ROOT / "morphogen" / "modules" / "observer-otel"), path]),
                                "KK_OTLP_PORT": str(s["otlp_port"]), "KK_OTLP_SECRET": s["otlp"],
                                "KK_OTLP_SOURCE": f"{otlp}/v1/metrics", "KK_OTLP_SERVICES": ",".join(SERVICES)},
                               cwd=ROOT / "morphogen" / "modules" / "observer-otel"),
        "ui": start("ui", [sys.executable, str(ROOT / "morphogen" / "ui" / "serve.py")],
                    {**base, "DATABASE_URL": auth, "KK_JWT_SECRET": s["jwt"], "PORT": str(s["ui_port"]),
                     "KK_UI_HOST": os.environ.get("MORPHOGEN_UI_HOST", "127.0.0.1"),
                     "KK_LOGIN_URL": f"host=127.0.0.1 port={s['db_port']} dbname={DB}"}),   # a person's own name and password
    }
    if COMPOSE:
        rt = ROOT / "morphogen" / "modules" / f"runtime-{RUNTIME}"
        engine = ("DOCKER_HOST",) if RUNTIME == "compose" else ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
        started["compose"] = start("compose", [sys.executable, "-m", f"runtime_{RUNTIME}", "--intent", str(repo), "--all"],
                                   {**base, **{k: os.environ[k] for k in engine if k in os.environ},
                                    **runtime_env(s, every)}, cwd=rt)
    f = HOME / "pids.json"
    f.write_text(json.dumps(started, indent=2) + "\n")
    time.sleep(3)
    dead = [k for k, v in started.items() if not ours(v)]
    if dead:
        die(f"stopped right away: {', '.join(dead)} (see {HOME / 'logs'})")
    say(f"Morphogen is up. The UI: http://127.0.0.1:{s['ui_port']}/ui/")
    if not any((repo / "systems").glob("*/compose.yaml")):
        say("next: `local.py person <your name>` to sign in, then describe a system (morphogen/deploy/LOCAL.md)")
    if a.foreground:
        foreground(started)


def foreground(started: dict) -> None:
    """Stay up until SIGTERM (or SIGINT), or until a process `up` started exits; then stop everything, Postgres
    included when it is embedded. Exits 0 on a signal, 1 when a process stopped by itself."""
    stop = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda n, _f: stop.append(n))
    gone = []
    while not stop and not gone:
        time.sleep(1)
        gone = [k for k, v in started.items() if not ours(v)]
    if gone:
        say(f"stopped by itself: {', '.join(gone)} (see {HOME / 'logs'}); stopping the rest")
    down(argparse.Namespace(db=True))
    sys.exit(1 if gone else 0)


def down(a) -> None:
    for name, entry in pids().items():
        if ours(entry):
            os.killpg(entry["pid"], signal.SIGTERM)
            say(f"stopped {name}")
    (HOME / "pids.json").unlink(missing_ok=True)
    if a.db and EMBEDDED:
        if subprocess.run(["pg_ctl", "-D", str(PGDATA), "status"], capture_output=True).returncode == 0:
            subprocess.run(["pg_ctl", "-D", str(PGDATA), "-w", "-m", "fast", "stop"], capture_output=True)
            say(f"stopped Postgres (the data stays in {PGDATA})")
    elif a.db:
        s = secret()
        subprocess.run(["docker", "stop", container(s)], capture_output=True)
        say(f"stopped Postgres (the data stays in the volume {volume(s)})")


def status(a) -> None:
    s = secret()
    if EMBEDDED:
        db = subprocess.run(["pg_ctl", "-D", str(PGDATA), "status"], capture_output=True, text=True)
        state = "running" if db.returncode == 0 else ("stopped" if (PGDATA / "PG_VERSION").exists() else "not created")
    else:
        db = subprocess.run(["docker", "inspect", "-f", "{{.State.Status}}", container(s)], capture_output=True, text=True)
        state = db.stdout.strip() or "not created"
    say(f"Postgres: {state} (127.0.0.1:{s['db_port']})")
    for name, entry in pids().items():
        say(f"{name}: {'running' if ours(entry) else 'stopped'} (pid {entry['pid']}, log {HOME / 'logs' / (name + '.log')})")
    if not COMPOSE:
        say(f"compose: run by the container's supervisor (log {HOME / 'logs' / 'compose.log'})")
    say(f"UI: http://127.0.0.1:{s['ui_port']}/ui/   intent: {HOME / 'intent'}")


# ------------------------------------------------------------------ people, agents, the design agent
def person(a) -> None:
    s = secret()
    out = subprocess.run([sys.executable, str(ROOT / "morphogen" / "ui" / "people.py"), "add", DB, a.name],
                         env={**os.environ, **pg_env(s), "PYTHONPATH": str(ROOT / "kernel" / "src")})
    if out.returncode == 0:
        import psycopg
        from psycopg import sql
        with psycopg.connect(conninfo(s), autocommit=True) as su:
            su.execute(sql.SQL("grant connect on database {} to {}").format(sql.Identifier(DB), sql.Identifier("person_" + a.name)))
        say(f"{a.name} can sign in at http://127.0.0.1:{s['ui_port']}/ui/")
    sys.exit(out.returncode)


def agent(a) -> None:
    if a.print:
        config, iri = agent_config(a.name, only=a.only)
        print(json.dumps(config))
        return
    f, iri = make_agent(a.name)
    say(f"{iri} has its own login. For Claude Code: claude --mcp-config {f}  (or `local.py claude {a.name}`)\n"
        f"(the interview skill: morphogen/skills/interview/SKILL.md)")


def make_agent(name: str) -> tuple[Path, str]:
    """An agent's own login and its MCP config, written to MORPHOGEN_HOME/mcp (0600)."""
    config, iri = agent_config(name)
    d = HOME / "mcp"
    d.mkdir(exist_ok=True, mode=0o700)
    f = d / f"{name}.json"
    f.touch(mode=0o600)
    f.write_text(json.dumps(config, indent=2) + "\n")
    return f, iri


def agent_config(name: str, only: bool = False) -> tuple[dict, str]:
    """An agent's own login (kk_agent: it proposes, it never reviews) and an MCP config that serves the record to it.
    A new password each time: an older config stops working. `only`: every other agent's login stops working too
    (password removed, sessions ended), for agents that share one OS user, as in the container, where one could
    otherwise keep another's config and propose as it."""
    import re
    import psycopg
    from psycopg import sql
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,30}", name):
        die("an agent's name: lower-case letters, digits and _, starting with a letter")
    s = secret()
    role, iri, pw = f"agent_{name}", f"urn:kk:agent:{name.replace('_', '-')}", secrets.token_urlsafe(32)
    with psycopg.connect(conninfo(s), autocommit=True) as su:
        other = su.execute("select db_role from kernel.agent where iri = %s", (iri,)).fetchone()
        if other and other[0] != role:
            die(f"{iri} is already the agent of {other[0]}")
        taken = su.execute("select iri from kernel.agent where db_role = %s and iri <> %s", (role, iri)).fetchone()
        if taken:
            die(f"{role} is already the login of {taken[0]}")
        verifier = su.pgconn.encrypt_password(pw.encode(), role.encode(), b"scram-sha-256").decode()
        exists = su.execute("select 1 from pg_roles where rolname = %s", (role,)).fetchone()
        su.execute(sql.SQL("{} role {} login password {}").format(
            sql.SQL("alter" if exists else "create"), sql.Identifier(role), sql.Literal(verifier)))
        su.execute(sql.SQL("grant kk_agent to {}").format(sql.Identifier(role)))
        su.execute(sql.SQL("grant connect on database {} to {}").format(sql.Identifier(DB), sql.Identifier(role)))
        if only:
            others = [r[0] for r in su.execute("select db_role from kernel.agent where db_role like 'agent\\_%%' and db_role <> %s",
                                               (role,)).fetchall()]
            for o in others:
                su.execute(sql.SQL("alter role {} password null").format(sql.Identifier(o)))
            su.execute("select pg_terminate_backend(pid) from pg_stat_activity where usename = any(%s)", (others,))
        su.execute("set role kk_owner")
        su.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, %s, 'software', %s) on conflict (iri) do nothing",
                   (iri, role, name))
    env = {"KK_DATABASE_URL": conninfo(s, user=role, password=pw),
           "PYTHONPATH": os.pathsep.join([str(ROOT / "kernel" / "src"), str(ROOT / "kernel" / "providers" / "kernel-mcp")])}
    return {"mcpServers": {"morphogen": {"command": sys.executable, "args": ["-m", "kernel_mcp"], "env": env}}}, iri


# What `claude` passes on from its own environment: nothing that opens the record or the services.
CLAUDE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TERM", "COLORTERM", "TZ", "TMPDIR", "USER", "SHELL",
              "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy", "NODE_EXTRA_CA_CERTS")


# Which endpoint and models Claude Code uses (a gateway such as LiteLLM, another provider's models): passed on to
# Claude Code alone, never to a service. ANTHROPIC_AUTH_TOKEN and ANTHROPIC_API_KEY are the gateway's or the API's key.
CLAUDE_MODEL_ENV = ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                    "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC")


def claude_env(base: dict) -> dict:
    """Claude Code's environment: `base` filtered to CLAUDE_ENV and CLAUDE_MODEL_ENV. It signs in as it always does
    (CLAUDE_CONFIG_DIR, or ~/.claude)."""
    return {k: v for k, v in base.items() if k in CLAUDE_ENV or k in CLAUDE_MODEL_ENV or k == "CLAUDE_CONFIG_DIR"}


def claude(a) -> None:
    """Claude Code as the agent NAME: its own login (a new one each time, `make_agent`) and the record over MCP,
    signed in as you are. Runs as you: on this machine it could read MORPHOGEN_HOME, so the container image, where
    it runs as a user of its own, is the stronger way (T24)."""
    f, iri = make_agent(a.name)
    binary = os.environ.get("MORPHOGEN_CLAUDE", "claude")
    if not shutil.which(binary):
        die(f"Claude Code is not on PATH ({binary})")
    say(f"Claude Code as {iri}; the interview skill: {ROOT / 'morphogen' / 'skills' / 'interview' / 'SKILL.md'}")
    os.execvpe(binary, [binary, "--mcp-config", str(f), *a.args], claude_env(dict(os.environ)))


def record(a) -> None:
    """`-` reads the conversation from standard input (as from outside a container)."""
    s = secret()
    (HOME / "artifacts").mkdir(exist_ok=True, mode=0o700)
    path = Path(a.file).resolve()
    if a.file == "-":
        import re
        if not re.fullmatch(r"[a-z0-9-]{1,40}", a.source):
            die("--source: a-z, 0-9 and -")
        (HOME / "inbox").mkdir(exist_ok=True, mode=0o700)
        path = HOME / "inbox" / f"{a.source}.jsonl"
        path.write_text(sys.stdin.read())
    out = subprocess.run([sys.executable, "-m", "interview_encoder", "--source", a.source, str(path)],
                         cwd=ROOT / "morphogen" / "modules" / "interview-encoder",
                         env={**os.environ, "DATABASE_URL": own(s, logins(s), "interview-encoder"),
                              "KK_ARTIFACTS": str(HOME / "artifacts"),
                              "PYTHONPATH": os.pathsep.join([str(ROOT / "morphogen" / "modules" / "interview-encoder"), str(ROOT / "kernel" / "src")])})
    sys.exit(out.returncode)


def propose(a) -> None:
    s = secret()
    out = subprocess.run([sys.executable, "-m", "design_blueprint", "propose", a.system],
                         cwd=ROOT / "morphogen" / "modules" / "design-blueprint",
                         env={**os.environ, "DATABASE_URL": own(s, logins(s), "design-blueprint"),
                              "KK_INTENT_DIR": str(HOME / "intent"),
                              "PYTHONPATH": os.pathsep.join([str(ROOT / "morphogen" / "modules" / "design-blueprint"),
                                                             str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "src")])})
    if out.returncode == 0:
        say(f"the plan waits in the UI's review lane: http://127.0.0.1:{s['ui_port']}/ui/")
    sys.exit(out.returncode)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Morphogen on a machine of your own.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("up")
    u.add_argument("--foreground", action="store_true", help="stay up; stop everything on SIGTERM")
    u.set_defaults(f=up)
    d = sub.add_parser("down")
    d.add_argument("--db", action="store_true", help="stop Postgres too")
    d.set_defaults(f=down)
    sub.add_parser("status").set_defaults(f=status)
    p = sub.add_parser("person")
    p.add_argument("name")
    p.set_defaults(f=person)
    g = sub.add_parser("agent")
    g.add_argument("name")
    g.add_argument("--print", action="store_true", help="print the MCP config instead of writing it")
    g.add_argument("--only", action="store_true", help="every other agent's login stops working")
    g.set_defaults(f=agent)
    c = sub.add_parser("claude")
    c.add_argument("name")
    c.add_argument("args", nargs=argparse.REMAINDER, help="passed on to Claude Code")
    c.set_defaults(f=claude)
    r = sub.add_parser("record")
    r.add_argument("file")
    r.add_argument("--source", required=True, help="a short name for the conversation (a-z, 0-9, -)")
    r.set_defaults(f=record)
    sub.add_parser("runtime-login", help="print the runtime's own login (for container.py)").set_defaults(f=runtime_login)
    q = sub.add_parser("propose")
    q.add_argument("system")
    q.set_defaults(f=propose)
    a = ap.parse_args(argv)
    a.f(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
