"""runtime-compose on a real Docker daemon (the runtime case set checks the rule on a stub engine,
morphogen/contract/slots/runtime): podinfo runs once a person approves its committed file, and is updated when a
committed change is approved, while an uncommitted edit, an unapproved commit or a refused file changes nothing; with
--all, a system committed and approved while the runtime runs starts on its own.

  PGHOST=... PGUSER=<superuser> python3 morphogen/tests/test_compose.py
      (Docker part: when a daemon answers; KK_REQUIRE_DOCKER=1 makes it required)
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
PROVIDER = ROOT / "morphogen" / "modules" / "runtime-compose"
sys.path[:0] = [str(ROOT / "morphogen" / "contract" / "slots" / "runtime"), str(ROOT / "kernel" / "contract" / "slots")]
from harness import Record, meta  # noqa: E402
from runner import World, sha  # noqa: E402

PODINFO = ROOT / "morphogen" / "intent" / "systems" / "podinfo" / "compose.yaml"
ROLE = meta(PROVIDER)["role"]


def check(cond, msg):
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
    if os.environ.get("KK_REQUIRE_DOCKER") == "1":
        raise SystemExit("CHECK FAILED: KK_REQUIRE_DOCKER=1 and no Docker daemon answers")
    print("skipped: no Docker daemon (the runtime case set checks the rule on a stub engine)")
    sys.exit(0)


def backend_env(project):
    cid = subprocess.run(["docker", "compose", "-p", project, "ps", "-q", "backend"], capture_output=True, text=True).stdout.strip()
    if not cid:
        return {}
    out = subprocess.run(["docker", "inspect", cid, "--format", "{{json .Config.Env}}"], capture_output=True, text=True).stdout
    return dict(x.split("=", 1) for x in json.loads(out or "[]"))


def start(w: World, rec: Record, tmp: Path, *args: str) -> subprocess.Popen:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")} | w.env(stub=False) | {
        "DATABASE_URL": rec.login(ROLE), "KK_ROLE": ROLE, "KK_RECONCILE_SECONDS": "1"}
    return subprocess.Popen([sys.executable, "-m", "runtime_compose", "--intent", str(w.intent), *args], cwd=PROVIDER, env=env,
                            stdout=open(tmp / "runtime.log", "w"), stderr=subprocess.STDOUT)


def events(tmp: Path):
    return [json.loads(x) for x in (tmp / "runtime.log").read_text().splitlines() if x.startswith("{")]


def wait(what, f, tmp: Path, timeout=300):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if got := f():
            return got
        time.sleep(1)
    raise SystemExit(f"CHECK FAILED: timed out waiting for {what}: {(tmp / 'runtime.log').read_text()[-1500:]}")


rec = Record("kkc_compose_docker", [PROVIDER])
tmp = Path(tempfile.mkdtemp())
project = f"kk-test-compose-{os.getpid()}"
p = None
try:
    w = World(PROVIDER, rec, tmp)
    first = PODINFO.read_text()
    w.commit("podinfo", first)
    w.approve(w.propose("urn:kk:system:podinfo", sha(first), shows=first))
    p = start(w, rec, tmp, "--system", "podinfo", "--project", project)
    wait("the system to start", lambda: [e for e in events(tmp) if e["event"] == "started"], tmp)
    check(backend_env(project).get("PODINFO_RANDOM_DELAY_MAX") == "600", "the approved, committed system runs (backend delay max 600)")
    edited = first.replace('PODINFO_RANDOM_DELAY_MAX: "600"', 'PODINFO_RANDOM_DELAY_MAX: "150"')
    w.commit("podinfo", edited, add=False)
    time.sleep(4)
    check(not [e for e in events(tmp) if e["event"] == "updated"] and backend_env(project).get("PODINFO_RANDOM_DELAY_MAX") == "600",
          "an uncommitted edit runs nothing")
    w.commit("podinfo", edited)
    wait("the refusal", lambda: [e for e in events(tmp) if e["event"] == "refused"], tmp)
    check(backend_env(project).get("PODINFO_RANDOM_DELAY_MAX") == "600", "a commit no one approved runs nothing; the system keeps running")
    w.approve(w.propose("urn:kk:node:podinfo:backend", 150, file_sha=sha(edited)))
    wait("the update", lambda: [e for e in events(tmp) if e["event"] == "updated"], tmp)
    check(backend_env(project).get("PODINFO_RANDOM_DELAY_MAX") == "150", "once the step naming the file is approved: the backend runs with 150")
    bad = edited.replace("  redis:\n", "  redis:\n    privileged: true\n")
    w.approve(w.propose("urn:kk:system:podinfo", sha(bad), shows=bad))
    w.commit("podinfo", bad)
    wait("the refusal", lambda: [e for e in events(tmp) if e["event"] == "refused" and "privileged" in e.get("reason", "")], tmp)
    check(backend_env(project).get("PODINFO_RANDOM_DELAY_MAX") == "150", "a file off the allow list changes nothing, approved or not")
finally:
    if p:
        p.terminate()
        p.wait(timeout=15)
    subprocess.run(["docker", "compose", "-p", project, "down", "-v", "-t", "1"], capture_output=True)
    rec.drop()
    shutil.rmtree(tmp, ignore_errors=True)

# --all: every system at HEAD, and one committed and approved while it runs (what the intent actuator and a person do
# for a described system) starts with no one starting a runtime for it.
REDIS = next(x.split("image:", 1)[1].strip() for x in PODINFO.read_text().splitlines() if "image: redis" in x)
rec = Record("kkc_compose_docker", [PROVIDER])
tmp = Path(tempfile.mkdtemp())
first, later = f"t{os.getpid()}a", f"t{os.getpid()}b"
text = f"services:\n  cache:\n    image: {REDIS}\n"
p = None
try:
    w = World(PROVIDER, rec, tmp)
    w.commit(first, text)
    w.approve(w.propose(f"urn:kk:system:{first}", sha(text), shows=text))
    p = start(w, rec, tmp, "--all")
    started = lambda name: [e for e in events(tmp) if e["event"] == "started" and e["system"] == name]  # noqa: E731
    wait("the first system to start", lambda: started(first), tmp)
    later_text = text + "    labels: {kk: later}\n"
    w.approve(w.propose(f"urn:kk:system:{later}", sha(later_text), shows=later_text))
    w.commit(later, later_text, add=False)
    time.sleep(3)
    check(not started(later), "--all: a system approved and written but not committed runs nothing")
    git = lambda *a: subprocess.run(["git", "-C", str(w.intent), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True)  # noqa: E731
    git("add", "-A")
    git("commit", "-qm", "a second system, approved")
    e = wait("the second system to start", lambda: started(later), tmp)
    check(e[0]["project"] == f"kk-{later}", "--all: a system committed later starts, as its own project")
finally:
    if p:
        p.terminate()
        p.wait(timeout=15)
    for name in (first, later):
        subprocess.run(["docker", "compose", "-p", f"kk-{name}", "down", "-v", "-t", "1"], capture_output=True)
    rec.drop()
    shutil.rmtree(tmp, ignore_errors=True)
print("runtime-compose on Docker: tests passed")
