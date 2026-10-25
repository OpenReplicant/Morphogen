"""T24: Morphogen's container image, end to end: built from morphogen/deploy/container/Containerfile, run with a
socket for the systems it starts, on throwaway volumes and a free port.

  serve     Postgres, the services and the UI run as the user morphogen, the compose runner as root (it alone
            holds the socket); every service runs from intent, none exiting; no secret in any log
  person    a person signs in through the published port
  claude    Claude Code runs as agent, signed in with the login copied from the read-only ~/.claude (a stand-in
            here, holding a hook too), and its own login to the record over MCP; it cannot reach the ~/.claude
            mount, the instance's secrets, the socket, a service's environment or another agent's login, nothing
            but the login is copied, nothing is written back, and no service reads the login; the pinned binary
            runs the same way
  describe  the agent describes a one-service system quoting a recorded conversation (sent on standard input),
            propose, a person approves over the UI, the actuator commits, the compose runner starts it
  restart   the container restarts with the record, the person and the login kept; `docker stop` ends it cleanly
  login     `morphogen login` runs Claude Code's own sign-in as agent, kept in the agent's config
  refuse    a socket mounted where others may reach it, or mounted anywhere else as well, is refused
  shared    a ~/.claude mounted writable for Claude Code to use as it is: refused without MORPHOGEN_CLAUDE_SHARED=1
            and for a system uid; with it, the agent takes the folder's owner and what it writes lands there
            (Docker only: rootless Podman needs keep-id, not run here)

  python3 morphogen/tests/test_container.py   (Docker; KK_REQUIRE_DOCKER=1 makes it required; KK_CONTAINER_IMAGE
  uses a built image; KK_BUILD_CA=<ca bundle> builds behind a proxy that re-signs TLS; for rootless Podman, as its
  user: KK_CONTAINER_ENGINE=podman KK_CONTAINER_SOCKET=$XDG_RUNTIME_DIR/podman/podman.sock)
"""
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REDIS = next(x.split("image:", 1)[1].strip() for x in (ROOT / "morphogen" / "intent" / "systems" / "podinfo" / "compose.yaml")
             .read_text().splitlines() if "image: redis" in x)
KKT = "https://w3id.org/knowledge-kernel/tosca#"
RDF_TYPE, LABEL = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "http://www.w3.org/2000/01/rdf-schema#label"
MAX, PROP = "https://www.irit.fr/recherches/MELODI/ontologies/BBO#maxValue", "http://www.w3.org/ns/sosa/observedProperty"
HOME = "/var/lib/morphogen"


def check(cond, msg):
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def wait(what, f, timeout=180, every=1.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if got := f():
            return got
        time.sleep(every)
    raise SystemExit(f"CHECK FAILED: timed out waiting for {what}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def post(url, body, token=None):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json",
                                 "Accept": "application/json, text/event-stream", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


ENGINE = os.environ.get("KK_CONTAINER_ENGINE", "docker")
SOCK = os.environ.get("KK_CONTAINER_SOCKET", "/var/run/docker.sock")


def docker(*args, stdin=None, timeout=600):
    return subprocess.run([ENGINE, *args], input=stdin, capture_output=True, text=True, timeout=timeout)


if docker("info").returncode != 0:
    if os.environ.get("KK_REQUIRE_DOCKER") == "1":
        raise SystemExit("CHECK FAILED: KK_REQUIRE_DOCKER=1 and no Docker daemon answers")
    print("skipped: no Docker daemon")
    sys.exit(0)

image = os.environ.get("KK_CONTAINER_IMAGE")
if not image:
    image = "morphogen:test"
    ca = os.environ.get("KK_BUILD_CA")
    out = subprocess.run([ENGINE, "build", "-q", "-f", str(ROOT / "morphogen" / "deploy" / "container" / "Containerfile"), "-t", image,
                          *(["--network", "host", "--secret", f"id=ca,src={ca}"] if ca else []), str(ROOT)],
                         capture_output=True, text=True, timeout=1800)
    check(out.returncode == 0, f"the image builds from the Containerfile, every download checked ({out.stderr.strip()[-800:]})")

tag = f"kk-ct-{os.getpid()}"
name, port = tag, free_port()
vols = {f"{tag}-home": HOME, f"{tag}-db": "/var/lib/postgresql/data", f"{tag}-agent": "/home/agent"}
SYSTEM = "store"                                   # kk-store; test_local's is kk-cache
# A stand-in for the person's ~/.claude: their login, and a hook Claude Code inside must never see or set.
claude_dir = Path(tempfile.mkdtemp(prefix="kk-ct-claude-"))
cred = "cred-" + secrets.token_urlsafe(24)
(claude_dir / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": cred}}))
(claude_dir / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "true"}]}]}}))
for f in claude_dir.iterdir():
    f.chmod(0o600)
claude_dir.chmod(0o700)
host_before = sorted((f.name, f.read_text()) for f in claude_dir.iterdir())
MOUNTS = ["-v", f"{SOCK}:/run/morphogen-socket/docker.sock", "-v", f"{claude_dir}:/run/morphogen-claude/host:ro"]


def run_container(*extra, cname=name):
    return docker("run", "-d", "--init", "--name", cname, "-p", f"127.0.0.1:{port}:8470", *[a for v, d in vols.items() for a in ("-v", f"{v}:{d}")],
                  *extra, image)


def ex(*args, user=None, stdin=None, env=()):
    return docker("exec", "-i", *(["-u", user] if user else []), *[a for e in env for a in ("-e", e)], name, *args, stdin=stdin)


ui = f"http://127.0.0.1:{port}"


def answers():
    try:
        return urllib.request.urlopen(ui + "/ui/", timeout=2).status == 200
    except OSError:
        return False


STUB = r'''#!/opt/venv/bin/python3
import json, os, pwd, socket, sys
conf = os.environ.get("CLAUDE_CONFIG_DIR", "")
out = {"user": pwd.getpwuid(os.getuid()).pw_name, "argv": sys.argv[1:], "cwd": os.getcwd(),
       "env": sorted(os.environ), "config_dir": conf, "copied": sorted(os.listdir(conf)),
       "mcp": sorted(os.listdir("/home/agent/.morphogen/mcp"))}
try:
    out["login"] = json.load(open(os.path.join(conf, ".credentials.json")))["claudeAiOauth"]["accessToken"]
    open(os.path.join(conf, "written-inside"), "w").write("a session file\n")
except OSError as e:
    out["login"] = repr(e)
def refused(f):
    try:
        f()
        return False
    except PermissionError:
        return True
out["secrets_refused"] = refused(lambda: open("/var/lib/morphogen/secrets.json").read())
out["host_refused"] = refused(lambda: os.listdir("/run/morphogen-claude/host"))
out["socket_refused"] = refused(lambda: socket.socket(socket.AF_UNIX).connect("/run/morphogen-socket/docker.sock"))
ui = [p for p in os.listdir("/proc") if p.isdigit() and b"serve.py" in open(f"/proc/{p}/cmdline", "rb").read()]
out["ui_environ_refused"] = bool(ui) and all(refused(lambda p=p: open(f"/proc/{p}/environ", "rb").read()) for p in ui)
cfg = sys.argv[sys.argv.index("--mcp-config") + 1] if "--mcp-config" in sys.argv else None
out["config"] = cfg and json.load(open(cfg))["mcpServers"]["morphogen"]["env"]["KK_DATABASE_URL"]
out["skill"] = os.path.exists(".claude/skills/interview/SKILL.md")
print(json.dumps(out))
'''

DESCRIBE = r'''
import json, sys, time
sys.path.insert(0, "/opt/morphogen/kernel/src")
from kk.lib import connect, run, submit
url, ops = json.loads(sys.stdin.read())
with connect(url=url) as me, me.cursor() as cur, run(cur, "urn:kk:module:interviewer") as (rid, _):
    res = submit(cur, {"idempotency_key": "store:describe", "attributed_to": "urn:kk:agent:interviewer",
                       "target_scope": "urn:kk:scope:default", "ops": ops}, rid)
for _ in range(120):
    with connect(url=url) as me:
        st = me.execute("select status from api.change_sets where id = %s", (res["id"],)).fetchone()[0]
    if st in ("applied", "invalid"):
        break
    time.sleep(1)
with connect(url=url) as me:
    try:
        me.execute("select api.review(%s::uuid, true, 'mine')", (res["id"],))
        refused = None
    except Exception as e:
        refused = getattr(e, "sqlstate", None)
print(json.dumps({"status": st, "review": refused}))
'''

try:
    out = run_container(*MOUNTS)
    check(out.returncode == 0, f"the container starts ({out.stderr.strip()[-300:]})")
    wait("the UI", answers, timeout=180)
    st = ex("morphogen", "status").stdout
    check(all(f"{p}: running" in st for p in ("reconcile", "observer-otel", "ui")) and "Postgres: running" in st, f"status: every process runs ({st})")
    ps = [line.split(None, 1) for line in ex("ps", "-eo", "user:12,args").stdout.splitlines()[1:]]
    by = lambda needle: {u for u, a in ps if needle in a}  # noqa: E731
    check(by("postgres -D") == {"morphogen"} and by("reconcile.py") == {"morphogen"} and by("serve.py") == {"morphogen"}
          and by("-m runtime_compose") == {"root"} and "agent" not in {u for u, _ in ps},
          "Postgres, the services and the UI run as morphogen; the compose runner alone as root; nothing as agent")
    rec = lambda: [json.loads(x) for x in ex("cat", f"{HOME}/logs/reconcile.log").stdout.splitlines() if x.startswith("{")]  # noqa: E731
    sys.path.insert(0, str(ROOT / "morphogen" / "deploy"))
    from local import SERVICES
    wait("every service", lambda: set(SERVICES) <= {e.get("provider") for e in rec() if e.get("event") == "started"}, timeout=90)
    time.sleep(12)
    bad = [e for e in rec() if e.get("event") in ("exited", "restarting", "failed", "refused")]
    check(not bad, f"the reconciler runs every service from intent, none exiting ({bad[:2]})")
    modes = ex("stat", "-c", "%U %a %n", HOME, f"{HOME}/secrets.json", "/home/agent", "/run/morphogen-socket").stdout.split("\n")
    check(modes[:4] == [f"morphogen 700 {HOME}", f"morphogen 600 {HOME}/secrets.json", "agent 700 /home/agent", "root 700 /run/morphogen-socket"],
          f"MORPHOGEN_HOME and the secrets are morphogen's alone, the agent's home its own, the socket root's ({modes})")
    s = json.loads(ex("cat", f"{HOME}/secrets.json").stdout)
    logs = ex("sh", "-c", f"cat {HOME}/logs/*").stdout + docker("logs", name).stdout + docker("logs", name).stderr
    leaked = [k for k in ("superuser", "logins", "otlp", "jwt", "authenticator") if s[k] in logs]
    check(not leaked, f"no secret in any log or the container's output ({leaked})")

    password = secrets.token_urlsafe(16)
    out = ex("morphogen", "person", "alice", stdin=password + "\n")
    check(out.returncode == 0, f"person: alice is added ({out.stderr.strip()[-300:]})")
    code, body = post(ui + "/ui/login", {"name": "alice", "password": password})
    check(code == 200 and body.get("token"), "alice signs in through the published port")
    token = body["token"]

    ex("sh", "-c", "cat > /usr/local/bin/claude-stub && chmod 755 /usr/local/bin/claude-stub", stdin=STUB)
    out = ex("morphogen", "claude", "designer", env=["MORPHOGEN_CLAUDE=/usr/local/bin/claude-stub"])   # another agent, first
    check(out.returncode == 0, f"claude: started, as agent, for another agent first ({out.stderr.strip()[-300:]})")
    designer_url = json.loads(out.stdout.strip().splitlines()[-1])["config"]
    model_env = ["ANTHROPIC_BASE_URL=http://127.0.0.1:4000", "ANTHROPIC_DEFAULT_HAIKU_MODEL=local/small"]
    out = ex("morphogen", "claude", "interviewer", "--print", "hello", env=["MORPHOGEN_CLAUDE=/usr/local/bin/claude-stub", *model_env])
    check(out.returncode == 0, f"claude: started ({out.stderr.strip()[-400:]})")
    got = json.loads(out.stdout.strip().splitlines()[-1])
    check(got["user"] == "agent" and got["config_dir"] == "/home/agent/.claude" and got["login"] == cred
          and got["argv"][-2:] == ["--print", "hello"], "Claude Code runs as agent, signed in with the person's login, the arguments passed on")
    check(".credentials.json" in got["copied"] and "settings.json" not in got["copied"] and got["host_refused"],
          "only the login is copied (no settings, no hooks), and the agent cannot reach the person's ~/.claude")
    check(got["mcp"] == ["interviewer.json"], "no other agent's config is beside its own")
    tried = ex("/opt/venv/bin/python3", "-c", "import sys, psycopg\ntry:\n    psycopg.connect(sys.stdin.read()).close(); print('in')\n"
               "except psycopg.OperationalError:\n    print('refused')", user="agent", stdin=designer_url)
    check(tried.stdout.strip() == "refused", "and the other agent's login, kept by a session before, no longer works (all agents share one user)")
    check({"ANTHROPIC_BASE_URL", "ANTHROPIC_DEFAULT_HAIKU_MODEL"} <= set(got["env"]),
          "the endpoint and model settings given to the exec reach Claude Code")
    check(ex("cat", "/home/agent/.claude/.credentials.json", user="morphogen").returncode != 0,
          "the user that runs the services cannot read the login")
    check(not [k for k in got["env"] if k.startswith(("KK_", "PG", "DATABASE")) or k in ("MORPHOGEN_HOME",)],
          f"Claude Code's environment holds nothing that opens the record or the services ({got['env']})")
    check(sorted((f.name, f.read_text()) for f in claude_dir.iterdir()) == host_before, "nothing is written to the person's ~/.claude")
    check(got["secrets_refused"] and got["socket_refused"] and got["ui_environ_refused"],
          "as agent it cannot read the instance's secrets, use the socket, or read the UI's environment")
    check("user=agent_interviewer" in got["config"] and got["skill"] and got["cwd"] == "/home/agent/work",
          "its MCP config holds the agent's own login; it works in /home/agent/work with the interview skill")
    check(ex("test", "-e", f"{HOME}/mcp/interviewer.json").returncode != 0, "MORPHOGEN_HOME keeps no copy of the agent's config")
    out = ex("morphogen", "login", env=["MORPHOGEN_CLAUDE=/usr/local/bin/claude-stub"])
    got = json.loads(out.stdout.strip().splitlines()[-1]) if out.returncode == 0 else {}
    check(got.get("user") == "agent" and got.get("argv") == ["auth", "login"] and got.get("config_dir") == "/home/agent/.claude",
          f"login: Claude Code's own sign-in runs as agent, into the agent's config ({got or out.stderr.strip()[-300:]})")
    out = ex("morphogen", "claude", "interviewer", "--version")
    check(out.returncode == 0 and "Claude Code" in out.stdout, f"the pinned Claude Code runs as agent the same way ({out.stdout.strip()} {out.stderr.strip()[-200:]})")

    # Claude Code runs commands as agent: a link it leaves in its home must not turn the next `claude` into a write of
    # root's elsewhere (here: taking over MORPHOGEN_HOME).
    ex("sh", "-c", "mv /home/agent/work /home/agent/work.old && ln -s /var/lib/morphogen /home/agent/work", user="agent")
    out = ex("morphogen", "claude", "interviewer", env=["MORPHOGEN_CLAUDE=/usr/local/bin/claude-stub"])
    check(out.returncode != 0 and ex("stat", "-c", "%U %a", HOME).stdout.strip() == "morphogen 700",
          "a link the agent left in its home does not hand it MORPHOGEN_HOME")
    ex("sh", "-c", "rm /home/agent/work && mv /home/agent/work.old /home/agent/work", user="agent")
    out = ex("morphogen", "claude", "interviewer", env=["MORPHOGEN_CLAUDE=/usr/local/bin/claude-stub"])   # each run, a new login
    check(out.returncode == 0, f"with the link gone, `claude` works again ({out.stdout.strip()[-200:]} {out.stderr.strip()[-400:]})")

    messages = [("1", "interviewer", "What system would you like Morphogen to run?"),
                ("2", "Alice", f"A store: one Redis service, {REDIS}."),
                ("3", "interviewer", "How slow may it get before something should change?"),
                ("4", "Alice", "Requests to the store should stay within 50 ms on average.")]
    chat = "".join(json.dumps({"id": i, "conversation": "store-intake", "author": a, "time": f"2026-11-01T09:0{i}:00Z", "text": t,
                               **({"kind": "agent"} if a == "interviewer" else {})}) + "\n" for i, a, t in messages)
    out = ex("morphogen", "record", "-", "--source", SYSTEM, stdin=chat)
    check(out.returncode == 0, f"record: the conversation, sent on standard input, is stored as notes ({out.stderr.strip()[-300:]})")
    m = lambda i: f"urn:kk:message:{SYSTEM}:store-intake:{i}"  # noqa: E731
    node, system = f"urn:kk:node:{SYSTEM}:redis", f"urn:kk:system:{SYSTEM}"

    def claim(subj, pred, obj, quote, msg, q=None):
        c = {"op": "add_claim", "subject": subj, "predicate": pred, "object": obj, "evidence_type": "extracted",
             "references": [{"source_uri": m(msg), "quote": quote}]}
        return {**c, "qualifiers": q} if q else c
    ops = [claim(system, RDF_TYPE, {"entity": KKT + "ServiceTemplate"}, "A store", "2"),
           claim(system, LABEL, {"value": {"@value": SYSTEM}}, "A store", "2"),
           claim(node, RDF_TYPE, {"entity": KKT + "NodeTemplate"}, "one Redis service", "2"),
           claim(node, LABEL, {"value": {"@value": "redis"}}, "Redis", "2"),
           claim(node, KKT + "memberOf", {"entity": system}, "A store: one Redis service", "2"),
           claim(node, KKT + "propertyValue", {"value": {"@value": REDIS}}, REDIS, "2", {KKT + "propertyName": "image"}),
           claim(node, MAX, {"value": {"@value": 0.05}}, "within 50 ms on average", "4", {PROP: "urn:kk:property:latency-seconds-mean"})]
    url = json.loads(ex("cat", "/home/agent/.morphogen/mcp/interviewer.json").stdout)["mcpServers"]["morphogen"]["env"]["KK_DATABASE_URL"]
    out = ex("/opt/venv/bin/python3", "-c", DESCRIBE, user="agent", stdin=json.dumps([url, ops]))
    got = json.loads(out.stdout.strip().splitlines()[-1]) if out.returncode == 0 else {}
    check(got.get("status") == "applied", f"the agent, as its own user and login, describes the system ({got} {out.stderr.strip()[-300:]})")
    check(got.get("review") == "42501", "the agent cannot review its own description")
    out = wait("a proposal", lambda: (o := ex("morphogen", "propose", SYSTEM)).returncode == 0 and o, timeout=120, every=5)
    plan = json.loads(out.stdout.strip().splitlines()[0])
    check(REDIS in plan["text"], "propose: the compose file waits in the review lane")
    code, body = post(ui + "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                    "params": {"name": "review", "arguments": {"change_set_id": plan["change_set"], "approve": True,
                                                                               "note": "run it"}}}, token)
    check(code == 200 and not body["result"].get("isError"), f"approve: alice approves it in the UI ({body})")
    show = lambda: ex("git", "-C", f"{HOME}/intent", "show", f"HEAD:systems/{SYSTEM}/compose.yaml", user="morphogen")  # noqa: E731
    wait("the intent actuator to commit the file", lambda: show().returncode == 0, timeout=120)
    check(show().stdout == plan["text"], "write: the approved text, committed to the instance's intent repository")
    events = lambda: [json.loads(x) for x in ex("cat", f"{HOME}/logs/compose.log").stdout.splitlines() if x.startswith("{")]  # noqa: E731
    e = wait("the system to start", lambda: [x for x in events() if x.get("system") == SYSTEM and x["event"] in ("started", "failed")],
             timeout=300)
    check(e[0]["event"] == "started" and e[0]["project"] == f"kk-{SYSTEM}", f"run: the compose runner starts the approved system ({e[0]})")
    running = docker("ps", "--filter", f"label=com.docker.compose.project=kk-{SYSTEM}", "--format", "{{.Image}}").stdout
    check(REDIS.split("@")[0].split(":")[0] in running, f"the system runs on this machine's container engine, beside Morphogen ({running.strip()})")

    out = docker("restart", "-t", "30", name)
    check(out.returncode == 0, "restart")
    wait("the UI again", answers, timeout=180)
    code, body = post(ui + "/ui/login", {"name": "alice", "password": password})
    check(code == 200 and body.get("token"), "the record is kept across a restart: alice signs in again")
    check(cred in ex("cat", "/home/agent/.claude/.credentials.json", user="agent").stdout, "after a restart the agent still reads the login")
    t0 = time.monotonic()
    out = docker("stop", "-t", "60", name)
    code = docker("inspect", "-f", "{{.State.ExitCode}}", name).stdout.strip()
    check(out.returncode == 0 and code == "0" and time.monotonic() - t0 < 50, f"docker stop ends it cleanly (exit {code})")
    check("stopped Postgres" in docker("logs", name).stdout, "Postgres is stopped, not killed")
    docker("rm", name)

    def refused(why, *mounts):
        out = run_container(*mounts, cname=name)
        wait("the refusal", lambda: docker("inspect", "-f", "{{.State.Status}}", name).stdout.strip() == "exited", timeout=60)
        said = docker("logs", name).stderr
        docker("rm", "-f", name)
        return out.returncode == 0 and why in said
    check(refused("must be root's alone", *MOUNTS, "--tmpfs", "/run/morphogen-socket:mode=0755"),
          "a socket mounted where others may reach it is refused")
    check(refused("a socket is mounted at", *MOUNTS, "-v", f"{SOCK}:/var/run/docker.sock"),
          "a container socket mounted anywhere else as well is refused")

    if ENGINE == "docker":
        shared = Path(tempfile.mkdtemp(prefix="kk-ct-shared-"))
        (shared / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": cred}}))
        SHARED_MOUNTS = ["-v", f"{SOCK}:/run/morphogen-socket/docker.sock", "-v", f"{shared}:/home/agent/.claude"]
        os.chown(shared, 999, 999)
        check(refused("a system or another user's id", *SHARED_MOUNTS, "-e", "MORPHOGEN_CLAUDE_SHARED=1"),
              "shared: a ~/.claude that shows as a system uid (postgres's) is refused")
        for f in (shared, shared / ".credentials.json"):
            os.chown(f, 4242, 4242)
        check(refused("MORPHOGEN_CLAUDE_SHARED=1", *SHARED_MOUNTS), "shared: refused without MORPHOGEN_CLAUDE_SHARED=1")
        out = run_container(*SHARED_MOUNTS, "-e", "MORPHOGEN_CLAUDE_SHARED=1")
        wait("the UI, shared", answers, timeout=180)
        ex("sh", "-c", "cat > /usr/local/bin/claude-stub && chmod 755 /usr/local/bin/claude-stub", stdin=STUB)
        out = ex("morphogen", "claude", "interviewer", env=["MORPHOGEN_CLAUDE=/usr/local/bin/claude-stub"])
        got = json.loads(out.stdout.strip().splitlines()[-1]) if out.returncode == 0 else {}
        w = shared / "written-inside"
        check(got.get("user") == "agent" and got.get("login") == cred and w.exists() and w.stat().st_uid == 4242,
              f"shared: the agent, as the folder's owner, uses that login and writes back to it ({got or out.stderr.strip()[-300:]})")
        check(ex("cat", "/home/agent/.claude/.credentials.json", user="morphogen").returncode != 0,
              "shared: the user that runs the services still cannot read it")
        docker("rm", "-f", name)
        shutil.rmtree(shared, ignore_errors=True)
finally:
    docker("rm", "-f", name)
    for c in docker("ps", "-aq", "--filter", f"label=com.docker.compose.project=kk-{SYSTEM}").stdout.split():
        docker("rm", "-f", "-v", c)
    for n in docker("network", "ls", "-q", "--filter", f"label=com.docker.compose.project=kk-{SYSTEM}").stdout.split():
        docker("network", "rm", n)
    for v in vols:
        docker("volume", "rm", v)
    shutil.rmtree(claude_dir, ignore_errors=True)
print("container image test passed")
