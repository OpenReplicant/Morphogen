"""Morphogen's container image (T24): the entry point, run as root inside the container, and the `morphogen` command.

  morphogen serve                 (the image's default) Postgres, the services and the UI as the user morphogen, and
                                  the compose runner, the one process that holds the container socket
  morphogen login                 sign Claude Code in (`claude auth login`, as the user agent): once, and again when
                                  the login expires; kept in the morphogen-agent volume
  morphogen claude NAME [ARGS]    Claude Code as the user agent: the agent NAME's own login over MCP, the interview
                                  skill
  morphogen person|agent|record|propose|status ...   local.py's commands, as the user morphogen

Three users, so what one holds the others cannot read:
  morphogen   Postgres, the services, the UI: MORPHOGEN_HOME (/var/lib/morphogen, 0700) holds the secrets
  agent       Claude Code (model-driven, runs commands): its home (/home/agent, 0700); it reaches the record only as
              its agent login, over MCP, and never the container socket (nor your ~/.claude, unless you share it)
  root        the compose runner, and the two mounts only root may enter: the container socket inside
              /run/morphogen-socket, and your ~/.claude, read-only, inside /run/morphogen-claude (each 0700), so
              their permissions on the host never decide who inside may use them
The services' environments (signing secrets, logins) are closed to the agent as another user's processes are.

Claude Code's sign-in, three ways:
  in the container (default)   `morphogen login`: Claude Code's own sign-in (it shows a code to paste), kept in the
                               agent's volume; nothing of yours is mounted
  copied, read-only            -v ~/.claude:/run/morphogen-claude/host:ro : at each `morphogen claude` root copies
                               your login (.credentials.json) into the agent's config, and nothing else; Claude Code
                               never sees your settings, hooks or history and cannot write to your ~/.claude (on
                               macOS the login is in the Keychain, not there: sign in with `morphogen login`)
  shared, writable             -v ~/.claude:/home/agent/.claude -e MORPHOGEN_CLAUDE_SHARED=1 : Claude Code uses your
                               ~/.claude as it is, and the user agent takes the uid and gid that own it (rootless
                               Podman: add --userns=keep-id:uid=10002,gid=10002). It can then read your history and
                               write your settings, hooks included, which your own Claude Code runs on your machine:
                               only for a ~/.claude you would hand to the agent anyway. Without the variable the
                               mount is refused.

Run (rootless Podman, recommended; Docker alike, with /var/run/docker.sock as the socket's source):
  podman run -d --init --name morphogen -p 127.0.0.1:8470:8470 \\
    -v morphogen:/var/lib/morphogen -v morphogen-db:/var/lib/postgresql/data -v morphogen-agent:/home/agent \\
    -v $XDG_RUNTIME_DIR/podman/podman.sock:/run/morphogen-socket/docker.sock morphogen:dev
Without the socket the record and the UI run, and approved systems wait (the compose runner does not start).
"""
from __future__ import annotations

import json
import os
import pwd
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / "morphogen" / "deploy" / "local.py"
HOME = Path(os.environ.get("MORPHOGEN_HOME", "/var/lib/morphogen"))
PGDATA = Path(os.environ.get("MORPHOGEN_PGDATA", "/var/lib/postgresql/data"))
SOCKET_DIR = Path("/run/morphogen-socket")
SOCKET = SOCKET_DIR / "docker.sock"
HOST_CLAUDE_DIR = Path("/run/morphogen-claude")
HOST_LOGIN = HOST_CLAUDE_DIR / "host" / ".credentials.json"
AGENT_HOME = Path("/home/agent")
CLAUDE_DIR = AGENT_HOME / ".claude"
SHARED = os.environ.get("MORPHOGEN_CLAUDE_SHARED") == "1"
PASS = ("PATH", "LANG", "LC_ALL", "TZ", "TERM", "MORPHOGEN_OPERATOR_NAME", "MORPHOGEN_OPERATOR_EMAIL",
        "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy")
sys.path.insert(0, str(LOCAL.parent))


def die(msg: str) -> None:
    raise SystemExit(f"morphogen: {msg}")


def user(name: str) -> pwd.struct_passwd:
    return pwd.getpwnam(name)


def env_for(name: str, **extra: str) -> dict:
    u = user(name)
    return {**{k: v for k, v in os.environ.items() if k in PASS}, "HOME": u.pw_dir, "USER": name, "LOGNAME": name, **extra}


def morphogen_env() -> dict:
    return env_for("morphogen", MORPHOGEN_HOME=str(HOME), MORPHOGEN_DB="embedded", MORPHOGEN_PGDATA=str(PGDATA),
                   MORPHOGEN_COMPOSE="external", MORPHOGEN_UI_HOST="0.0.0.0")


def drop(name: str) -> None:
    """Become `name` for good: its groups only, then its gid and uid."""
    u = user(name)
    os.setgroups([])
    os.setgid(u.pw_gid)
    os.setuid(u.pw_uid)


def as_user(name: str, argv: list[str], **kw) -> subprocess.Popen:
    u = user(name)
    return subprocess.Popen(argv, user=u.pw_uid, group=u.pw_gid, extra_groups=[], **kw)


def own(path: Path, name: str, mode: int) -> None:
    """For mount points only (the volumes), which no user inside can replace with a link."""
    u = user(name)
    path.mkdir(parents=True, exist_ok=True)
    os.chown(path, u.pw_uid, u.pw_gid)
    path.chmod(mode)


def mounts() -> list[str]:
    """Every mount point, as mountinfo writes them with octal escapes (a space is \\040) decoded."""
    import re
    with open("/proc/self/mountinfo") as f:
        return [re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), line.split()[4]) for line in f]


def root_only(d: Path) -> None:
    st = d.stat()
    if st.st_uid != 0 or stat.S_IMODE(st.st_mode) & 0o077:
        die(f"{d} must be root's alone (0700): mount into it, not over it")


def guard_mounts() -> bool:
    """The socket and your ~/.claude are mounted where only root reaches them, and no container socket is mounted
    anywhere else (there its own permissions would decide who inside may use it). True when the socket is there."""
    root_only(SOCKET_DIR)
    root_only(HOST_CLAUDE_DIR)
    elsewhere = [m for m in mounts() if m != str(SOCKET) and Path(m).exists() and stat.S_ISSOCK(Path(m).lstat().st_mode)]
    if elsewhere:
        die(f"a socket is mounted at {', '.join(elsewhere)}: mount the container socket at {SOCKET} only")
    return SOCKET.exists() and stat.S_ISSOCK(SOCKET.stat().st_mode)


# ------------------------------------------------------------------ serve
def serve() -> int:
    if os.getuid() != 0:
        die("`serve` runs as root inside the container (it starts each part as its own user)")
    own(HOME, "morphogen", 0o700)
    own(PGDATA, "morphogen", 0o700)
    share_claude_dir()
    own(AGENT_HOME, "agent", 0o700)
    socket = guard_mounts()
    log = lambda m: print(f"morphogen: {m}", flush=True)  # noqa: E731
    (HOME / "pids.json").unlink(missing_ok=True)    # left by an unclean stop, it would start the compose runner early
    up = as_user("morphogen", [sys.executable, str(LOCAL), "up", "--foreground"], env=morphogen_env(), cwd=str(HOME))
    procs = {"up": up}
    stop = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda n, _f: stop.append(n))
    if socket:
        while not stop and up.poll() is None and not (HOME / "pids.json").exists():
            time.sleep(1)                      # `up` writes pids.json once the intent repository and the services exist
        if up.poll() is None and not stop:
            repo = str(HOME / "intent")
            # Root reads a repository morphogen writes: git's own guard is lifted for it alone, and nothing the
            # repository's config names (hooks, fsmonitor, system or global config) runs as root.
            git = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_COUNT": "3",
                   "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": repo,
                   "GIT_CONFIG_KEY_1": "core.hooksPath", "GIT_CONFIG_VALUE_1": "/dev/null",
                   "GIT_CONFIG_KEY_2": "core.fsmonitor", "GIT_CONFIG_VALUE_2": "false"}
            runner = subprocess.Popen(
                [sys.executable, str(ROOT / "morphogen" / "deploy" / "compose.py"), "--intent", repo, "--all"],
                env={"PATH": os.environ["PATH"], "HOME": "/root", "DOCKER_HOST": f"unix://{SOCKET}", **git},
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd="/")
            # Its log is written by morphogen, never opened by root in a folder morphogen controls.
            procs["compose-log"] = as_user("morphogen", ["tee", "-a", str(HOME / "logs" / "compose.log")],
                                           stdin=runner.stdout, stdout=subprocess.DEVNULL)
            runner.stdout.close()
            procs["compose"] = runner
            log("the compose runner holds the container socket")
    else:
        log(f"no container socket at {SOCKET}: approved systems are committed but not started")
    while not stop and all(p.poll() is None for p in procs.values()):
        time.sleep(1)
    for p in procs.values():
        if p.poll() is None:
            p.terminate()
    for p in procs.values():
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
    return 0 if stop else 1


# ------------------------------------------------------------------ the agent
def share_claude_dir() -> None:
    """A ~/.claude mounted at /home/agent/.claude is used as it is, only with MORPHOGEN_CLAUDE_SHARED=1; the user
    agent then takes the uid and gid that own it, so Claude Code reads and refreshes it as its owner does. Refused
    when that uid or gid is a system one (below 1000) or another user's or group's in the image: the agent would
    become root, postgres, morphogen or the like."""
    import grp
    if str(CLAUDE_DIR) not in mounts():
        return
    if not SHARED:
        die(f"~/.claude is mounted at {CLAUDE_DIR}, which hands Claude Code all of it, writable (settings and hooks your "
            f"own Claude Code runs): set MORPHOGEN_CLAUDE_SHARED=1 to mean that, or mount it read-only inside "
            f"{HOST_CLAUDE_DIR / 'host'} to copy the login alone")
    st, a = CLAUDE_DIR.stat(), user("agent")
    uid_owner = next((u.pw_name for u in pwd.getpwall() if u.pw_uid == st.st_uid), None)
    gid_owner = next((g.gr_name for g in grp.getgrall() if g.gr_gid == st.st_gid), None)
    if st.st_uid < 1000 or st.st_gid < 1000 or uid_owner not in (None, "agent") or gid_owner not in (None, "agent"):
        die(f"{CLAUDE_DIR} shows as uid {st.st_uid}, gid {st.st_gid} inside, a system or another user's id: mount a "
            "folder you own (rootless Podman: add --userns=keep-id:uid=10002,gid=10002)")
    if (a.pw_uid, a.pw_gid) == (st.st_uid, st.st_gid):
        return
    old = f"{a.pw_uid}:{a.pw_gid}"
    # The entries are edited, not usermod'd: usermod -u would walk the agent's home as root, links and all.
    for path, field, value in (("/etc/passwd", (2, 3), (st.st_uid, st.st_gid)), ("/etc/group", (2,), (st.st_gid,))):
        lines = Path(path).read_text().splitlines()
        for i, line in enumerate(lines):
            parts = line.split(":")
            if parts[0] == "agent":
                for f, v in zip(field, value):
                    parts[f] = str(v)
                lines[i] = ":".join(parts)
        tmp = Path(path + ".morphogen")
        tmp.write_text("\n".join(lines) + "\n")
        tmp.chmod(0o644)
        os.replace(tmp, path)                      # whole or not at all: a crash never leaves it cut short
    # What the agent kept in its volume under its old ids becomes its own again: lchown only, links not followed,
    # and the shared folder left as it is.
    for child in AGENT_HOME.iterdir():
        if child != CLAUDE_DIR:
            subprocess.run(["chown", "-R", "-h", f"--from={old}", f"{st.st_uid}:{st.st_gid}", str(child)], check=True)
    print(f"morphogen: the agent user takes uid {st.st_uid} and gid {st.st_gid}, the owner of the shared ~/.claude", flush=True)


def read_plain(path: Path, owner: int | None, limit: int = 1 << 20) -> str | None:
    """A regular file's text, never through a link, owned by `owner` if given; None when there is none."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(fd) as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or (owner is not None and st.st_uid != owner) or st.st_size > limit:
            die(f"{path} is not a plain file{'' if owner is None else ' of its own user'}")
        return f.read()


def claude(name: str, args: list[str]) -> int:
    """The agent's own login and MCP config are made as morphogen and handed over on a pipe (MORPHOGEN_HOME keeps
    no copy; every other agent's login stops working, since all agents share the user agent), with your Claude login
    from the read-only mount; everything under /home/agent is then written as agent,
    never as root, so a link the agent left there cannot turn into a write of root's elsewhere. Claude Code runs as
    agent in /home/agent/work, with the interview skill and no other agent's config beside its own."""
    out = as_user("morphogen", [sys.executable, str(LOCAL), "agent", name, "--print", "--only"], env=morphogen_env(),
                  cwd=str(HOME), stdout=subprocess.PIPE, text=True)
    printed, _ = out.communicate()
    if out.returncode:
        return out.returncode
    config = json.loads(printed.strip().splitlines()[-1])
    root_only(HOST_CLAUDE_DIR)
    login = None if SHARED else read_plain(HOST_LOGIN, None)
    host_mtime = HOST_LOGIN.lstat().st_mtime if login is not None else 0
    if login is not None:
        json.loads(login)                          # a login file, not anything else the mount holds
    skill = (ROOT / "morphogen" / "skills" / "interview" / "SKILL.md").read_text()
    own(AGENT_HOME, "agent", 0o700)               # the volume's mount point: not a path the agent can replace
    env = agent_env()
    binary = os.environ.get("MORPHOGEN_CLAUDE", "claude")
    drop("agent")
    os.umask(0o077)
    work, mcp = AGENT_HOME / "work", AGENT_HOME / ".morphogen" / "mcp"
    for d in (mcp, CLAUDE_DIR, work / ".claude" / "skills" / "interview"):
        d.mkdir(parents=True, exist_ok=True)
    for other in mcp.iterdir():                    # each agent's login is used by its own run only
        other.unlink()
    cfg = mcp / f"{name}.json"
    cfg.write_text(json.dumps(config, indent=2) + "\n")
    creds = CLAUDE_DIR / ".credentials.json"
    if login is not None and (not creds.exists() or creds.stat().st_mtime < host_mtime):
        creds.unlink(missing_ok=True)              # the host's login, when newer than the copy Claude Code refreshed
        creds.write_text(login)
    (work / ".claude" / "skills" / "interview" / "SKILL.md").write_text(skill)
    os.chdir(work)
    os.execvpe(binary, [binary, "--mcp-config", str(cfg), *args], env)
    return 1


def agent_env() -> dict:
    """Claude Code's environment, with the endpoint and model settings given to the container or to this exec
    (local.CLAUDE_MODEL_ENV), which no service receives."""
    from local import CLAUDE_MODEL_ENV, claude_env
    return claude_env({**env_for("agent", CLAUDE_CONFIG_DIR=str(CLAUDE_DIR)),
                       **{k: v for k, v in os.environ.items() if k in CLAUDE_MODEL_ENV}})


def login(args: list[str]) -> int:
    """Claude Code's own sign-in, as agent, kept in its config (the agent's volume, or a shared ~/.claude)."""
    own(AGENT_HOME, "agent", 0o700)
    env = agent_env()
    binary = os.environ.get("MORPHOGEN_CLAUDE", "claude")
    drop("agent")
    os.umask(0o077)
    CLAUDE_DIR.mkdir(exist_ok=True)
    os.chdir(AGENT_HOME)
    os.execvpe(binary, [binary, "auth", "login", *args], env)
    return 1


def main(argv: list[str]) -> int:
    cmd, rest = (argv[0], argv[1:]) if argv else ("serve", [])
    if os.getuid() != 0:                         # `docker exec -u morphogen`: local.py's commands, as you are
        os.execv(sys.executable, [sys.executable, str(LOCAL), *argv])
    if cmd == "serve":
        return serve()
    if cmd == "login":
        return login(rest)
    if cmd == "claude":
        if not rest:
            die("morphogen claude NAME [ARGS for Claude Code]")
        return claude(rest[0], rest[1:])
    if cmd in ("person", "agent", "record", "propose", "status", "down"):
        os.chdir(HOME)
        env = morphogen_env()
        drop("morphogen")
        os.execve(sys.executable, [sys.executable, str(LOCAL), cmd, *rest], env)
    die(f"unknown command {cmd!r}: serve, login, claude, person, agent, record, propose, status")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
