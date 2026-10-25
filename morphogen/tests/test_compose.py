"""deploy/compose.py: the allow list, then (with Docker) podinfo run from its committed compose file and
updated when a commit changes a setting, while an uncommitted edit or a refused file changes nothing; with
--all, a system committed while the runner runs starts on its own.

  python3 morphogen/tests/test_compose.py   (Docker part: when a daemon answers; KK_REQUIRE_DOCKER=1 makes it required)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "morphogen" / "deploy"))
from compose import refusal  # noqa: E402

PODINFO = ROOT / "morphogen" / "intent" / "systems" / "podinfo" / "compose.yaml"
IMG = "redis:7.4.2-alpine@sha256:" + "0" * 64


def check(cond, msg):
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def svc(**kw):
    return "services:\n  a:\n" + "".join(f"    {k}: {v}\n" for k, v in {"image": IMG, **kw}.items())


check(refusal(PODINFO.read_text()) is None, "podinfo's compose file is on the allow list")
import compose  # noqa: E402
sys.path.insert(0, str(ROOT / "morphogen" / "modules" / "map-gaps"))
from map_gaps import gaps  # noqa: E402
check(gaps.DIGEST.pattern == compose.DIGEST.pattern, "the gap finder asks for a pin exactly as the compose runner requires one")
for text, why in [(svc(privileged="true"), "privileged not allowed"), (svc(volumes='["/:/host"]'), "volumes not allowed"),
                  (svc(build="."), "build not allowed"), (svc(env_file="/etc/shadow"), "env_file not allowed"),
                  (svc(network_mode="host"), "network_mode not allowed"), (svc(cap_add="[SYS_ADMIN]"), "cap_add not allowed"),
                  (svc(extends="{file: x.yaml, service: b}"), "extends not allowed"),
                  ("services:\n  a:\n    image: redis:7.4.2-alpine\n", "pinned by digest"),
                  (svc(ports='["9898:9898"]'), "127.0.0.1"), (svc(ports='["0.0.0.0:1:2"]'), "127.0.0.1"),
                  (svc(environment="{A: ${HOME}}"), "no $"), (svc(environment="[DOCKER_HOST]"), "a name alone"),
                  (svc(environment="{HOME: }"), "a name alone"), (svc(**{"1": "x"}), "1 not allowed"), (svc() + "volumes: {x: {}}\n", "nothing else at the top"),
                  ("include: [x.yaml]\nservices: {}\n", "nothing else at the top"), ("services:\n  A B: {image: x}\n", "lower-case")]:
    got = refusal(text)
    check(got is not None and why in got, f"refused: {why} ({text.splitlines()[-1].strip()[:40]})")

if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
    if os.environ.get("KK_REQUIRE_DOCKER") == "1":
        raise SystemExit("CHECK FAILED: KK_REQUIRE_DOCKER=1 and no Docker daemon answers")
    print("skipped: no Docker daemon (the allow list was checked)")
    sys.exit(0)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          check=True, capture_output=True, text=True).stdout


def backend_env(project):
    cid = subprocess.run(["docker", "compose", "-p", project, "ps", "-q", "backend"], capture_output=True, text=True).stdout.strip()
    if not cid:
        return {}
    out = subprocess.run(["docker", "inspect", cid, "--format", "{{json .Config.Env}}"], capture_output=True, text=True).stdout
    return dict(x.split("=", 1) for x in json.loads(out or "[]"))


tmp = Path(tempfile.mkdtemp())
intent = tmp / "intent"
(intent / "systems" / "podinfo").mkdir(parents=True)
shutil.copy(PODINFO, intent / "systems" / "podinfo" / "compose.yaml")
f = intent / "systems" / "podinfo" / "compose.yaml"
git(intent, "init", "-q")
git(intent, "add", "-A")
git(intent, "commit", "-qm", "import podinfo")
project = f"kk-test-compose-{os.getpid()}"
log = open(tmp / "compose.log", "w+")
p = subprocess.Popen([sys.executable, str(ROOT / "morphogen" / "deploy" / "compose.py"), "--intent", str(intent),
                      "--system", "podinfo", "--project", project], env={**os.environ, "KK_RECONCILE_SECONDS": "1"},
                     stdout=log, stderr=subprocess.STDOUT)


def events():
    log.flush()
    return [json.loads(x) for x in (tmp / "compose.log").read_text().splitlines() if x.startswith("{")]


def wait(what, f, timeout=300):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if got := f():
            return got
        time.sleep(1)
    raise SystemExit(f"CHECK FAILED: timed out waiting for {what}: {(tmp / 'compose.log').read_text()[-1500:]}")


try:
    wait("the system to start", lambda: [e for e in events() if e["event"] == "started"])
    check(backend_env(project).get("PODINFO_RANDOM_DELAY_MAX") == "600", "the committed system runs (backend delay max 600)")
    f.write_text(f.read_text().replace('PODINFO_RANDOM_DELAY_MAX: "600"', 'PODINFO_RANDOM_DELAY_MAX: "150"'))
    time.sleep(4)
    check(not [e for e in events() if e["event"] == "updated"] and backend_env(project).get("PODINFO_RANDOM_DELAY_MAX") == "600",
          "an uncommitted edit runs nothing")
    git(intent, "commit", "-qam", "delay max 150")
    wait("the update", lambda: [e for e in events() if e["event"] == "updated"])
    check(backend_env(project).get("PODINFO_RANDOM_DELAY_MAX") == "150", "a committed change: the backend now runs with 150")
    f.write_text(f.read_text().replace("  redis:\n", "  redis:\n    privileged: true\n"))
    git(intent, "commit", "-qam", "privileged redis")
    wait("the refusal", lambda: [e for e in events() if e["event"] == "refused"])
    check(backend_env(project).get("PODINFO_RANDOM_DELAY_MAX") == "150", "a refused file changes nothing; the system keeps running")
finally:
    p.terminate()
    p.wait(timeout=15)
    subprocess.run(["docker", "compose", "-p", project, "down", "-v", "-t", "1"], capture_output=True)
    shutil.rmtree(tmp, ignore_errors=True)

# --all: every system at HEAD, and one committed while it runs (what the intent actuator does once a person
# approves a described system's file) starts with no one starting a runner for it.
REDIS = next(x.split("image:", 1)[1].strip() for x in PODINFO.read_text().splitlines() if "image: redis" in x)
tmp = Path(tempfile.mkdtemp())
intent = tmp / "intent"
first, later = f"t{os.getpid()}a", f"t{os.getpid()}b"
for name in (first, later):
    (intent / "systems" / name).mkdir(parents=True)
(intent / "systems" / first / "compose.yaml").write_text(f"services:\n  cache:\n    image: {REDIS}\n")
git(intent, "init", "-q")
git(intent, "add", "-A")
git(intent, "commit", "-qm", "one system")
log = open(tmp / "compose.log", "w+")
p = subprocess.Popen([sys.executable, str(ROOT / "morphogen" / "deploy" / "compose.py"), "--intent", str(intent), "--all"],
                     env={**os.environ, "KK_RECONCILE_SECONDS": "1"}, stdout=log, stderr=subprocess.STDOUT)
try:
    started = lambda name: [e for e in events() if e["event"] == "started" and e["system"] == name]  # noqa: E731
    wait("the first system to start", lambda: started(first))
    check(not started(later), "--all: the committed system runs; a directory with nothing committed in it runs nothing")
    (intent / "systems" / later / "compose.yaml").write_text(f"services:\n  cache:\n    image: {REDIS}\n")
    time.sleep(3)
    check(not started(later), "--all: a system written but not committed runs nothing")
    git(intent, "add", "-A")
    git(intent, "commit", "-qm", "a second system, approved")
    e = wait("the second system to start", lambda: started(later))
    check(e[0]["project"] == f"kk-{later}", "--all: a system committed later starts, as its own project")
finally:
    p.terminate()
    p.wait(timeout=15)
    for name in (first, later):
        subprocess.run(["docker", "compose", "-p", f"kk-{name}", "down", "-v", "-t", "1"], capture_output=True)
    shutil.rmtree(tmp, ignore_errors=True)
print("compose reconciler tests passed")
