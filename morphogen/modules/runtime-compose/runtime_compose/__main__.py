"""The runtime slot's Compose provider (T27, R5-O9 as amended by R5-42 (c); first written as deploy/compose.py, R5-25):
run each managed system's compose file as committed in intent, and again whenever the commit changes it, but only
a file a person approved (T26).

  python3 -m runtime_compose --intent DIR --system NAME [--project NAME]
  python3 -m runtime_compose --intent DIR --all        every system at HEAD, as project kk-<system>

The file is read from the commit at HEAD, never the work tree, and run only when
  it is on the allow list (`refusal`): only `services`; per service only image (pinned by digest), command,
  entrypoint, environment, ports (published on 127.0.0.1), depends_on, healthcheck, restart, labels, working_dir
  and user; no `$` anywhere (compose would fill it from this process's environment); anything else (privileged,
  cap_add, devices, volumes, build, env_file, network_mode, extends, ...) is refused; and
  a person-approved plan step authorises it (morphogen.plans.approval): a create or adopt step on the system whose
  value is the file's sha256 and whose plan label, decided with it, shows the whole file; or a setting step on one of
  its nodes, for an action on the fixed list (from the code) within its bounds, when the file is the one this runtime
  last ran for the system with that value set, derived here and never taken from the step's own hash; and
  its approval is no older than the latest approval among the files this runtime has run (from its own run
  records: going back to an older file needs a new approval).
Who committed the file does not matter: a file committed by anything but the intent actuator, or edited after its
approval, names no approved step and is refused, and the system keeps running as it was. With --all, a system
whose approved file is committed later starts without anyone starting a runner for it: the design loop ends with
the system running. One system's failure (a refused file, an `up` that fails or hangs past its timeout) is that
system's event; the others carry on. What a person approves is what runs; who committed it does not matter. This
holds against agents acting through their own logins, not against the OS user that runs the services and holds the
record's superuser password. The file is copied into a fresh private directory and compose runs there with
only PATH, HOME and DOCKER_HOST, so no `.env` file or variable of ours reaches it (an environment entry without a
value, which would pass one on, is refused). A file removed from HEAD leaves the system running (it is someone
else's: stopping it is a person's call, R5-25) and says so. Each file it runs is a run of its own (plan_step: the
approving step; outputs: the system, the sha256 applied and the approval's time; used: the step's claims), which is
how it knows what it ran before.
Prints one JSON line per event. Every KK_RECONCILE_SECONDS (default 2) it re-reads; KK_ONCE=1, one pass. Without
the record it runs nothing new (`record-unreachable`). Needs Docker (or Podman's Docker-compatible socket).
Env: DATABASE_URL (its own login, or one that may SET ROLE to KK_ROLE), KK_ROLE (default kkm_runtime_compose),
KK_INTENT_DIR (when --intent is not given), DOCKER_HOST.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import psycopg
import yaml

from kk.lib import connect, run
from morphogen import plans
from morphogen.policy import actions

NAME = re.compile(r"[a-z0-9][a-z0-9_.-]*")
SERVICE_KEYS = {"image", "command", "entrypoint", "environment", "ports", "depends_on", "healthcheck", "restart",
                "labels", "working_dir", "user"}
DIGEST = re.compile(r"[^\s@]+@sha256:[0-9a-f]{64}")
RETRY_SECONDS = float(os.environ.get("KK_COMPOSE_RETRY_SECONDS", "60"))
MODULE = "urn:kk:module:runtime-compose"
PORT = re.compile(r"127\.0\.0\.1:(\d{1,5})?:\d{1,5}(/(tcp|udp))?")


def committed(intent: Path, system: str) -> bytes | None:
    """The system's compose file at HEAD, or None when HEAD has none."""
    out = subprocess.run(["git", "-C", str(intent), "show", f"HEAD:./systems/{system}/compose.yaml"], capture_output=True)
    return out.stdout if out.returncode == 0 else None


def refusal(text: str) -> str | None:
    """Why this compose file is not run, or None."""
    if "$" in text:
        return "no $ anywhere: compose would interpolate it from the reconciler's environment"
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return f"not YAML: {str(e)[:100]}"
    if not isinstance(doc, dict) or set(doc) != {"services"} or not isinstance(doc["services"], dict) or not doc["services"]:
        return "the file must have services and nothing else at the top"
    for name, svc in doc["services"].items():
        if not isinstance(name, str) or not NAME.fullmatch(name) or not isinstance(svc, dict):
            return f"service {name!r}: a lower-case name and a mapping"
        if extra := sorted(str(k) for k in svc if k not in SERVICE_KEYS):
            return f"service {name}: {', '.join(extra)} not allowed"
        if not isinstance(svc.get("image"), str) or not DIGEST.fullmatch(svc["image"]):
            return f"service {name}: the image must be pinned by digest (name@sha256:...)"
        ports = svc.get("ports") or []
        if not isinstance(ports, list) or not all(isinstance(p, str) and PORT.fullmatch(p) for p in ports):
            return f"service {name}: ports must be published on 127.0.0.1 only (\"127.0.0.1:[host]:container\")"
        env = svc.get("environment") or {}
        # A name without a value (`- HOME`, `HOME:`) makes compose pass on this process's own variable.
        if isinstance(env, dict):
            if not all(isinstance(k, str) and isinstance(v, (str, int, float, bool)) for k, v in env.items()):
                return f"service {name}: environment entries must be NAME: value (a name alone passes ours on)"
        elif not isinstance(env, list) or not all(isinstance(x, str) and "=" in x for x in env):
            return f"service {name}: environment must be a mapping or a list of NAME=value (a name alone passes ours on)"
    return None


def compose(project: str, workdir: Path, *args: str, timeout: float = 300) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "DOCKER_HOST")}
    return subprocess.run(["docker", "compose", "-p", project, "--project-directory", str(workdir), "-f",
                           str(workdir / "compose.yaml"), *args], cwd=workdir, env=env, capture_output=True, text=True,
                          timeout=timeout)


def apply(project: str, text: bytes) -> subprocess.CompletedProcess:
    """`up -d --wait --remove-orphans` on this content, from a fresh private directory."""
    with tempfile.TemporaryDirectory(prefix="kk-compose-") as d:
        workdir = Path(d)
        workdir.chmod(0o700)
        (workdir / "compose.yaml").write_bytes(text)
        return compose(project, workdir, "up", "-d", "--wait", "--remove-orphans")


def systems(intent: Path) -> list[str]:
    """The systems with a directory under systems/ at HEAD (names compose accepts only)."""
    out = subprocess.run(["git", "-C", str(intent), "ls-tree", "-d", "-z", "--name-only", "HEAD:./systems"],
                         capture_output=True, text=True)
    return sorted(n for n in out.stdout.split("\0") if NAME.fullmatch(n)) if out.returncode == 0 else []


STEPS = """select id, subject, predicate, object_entity, object_value, qualifiers, change_set from api.claims
           where status <> 'deprecated' and subject in
             (select subject from api.claims where predicate = %s and status <> 'deprecated')"""


LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
# The fixed action list as the code has it, never the instance's intent repository (which processes can write).
ACTIONS = actions(Path(__file__).resolve().parents[3] / "intent")


def approvals(cur) -> dict:
    """What a pass needs from the record: the plan steps (morphogen.plans.steps) with people's decisions, the plans'
    labels per change set, and from this runtime's own runs, per system, the latest file it ran (sha256) and the
    latest decision among the files it ran (the floor: a file approved before it does not run again without a new
    approval). The floor comes from its own records only, so withdrawing an approving step cannot lower it."""
    cur.execute(STEPS, (plans.PPLAN_STEP_OF,))
    cols = [d.name for d in cur.description]
    claims = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.execute("""select id::text, 'review', decided_by, submitted_by, 'applied', decided_at from api.review_decisions
                   where id = any(%s::uuid[])""", (sorted({str(c["change_set"]) for c in claims}),))
    sets = {r[0]: dict(zip(("lane", "decided_by", "submitted_by", "status", "decided_at"), r[1:])) for r in cur.fetchall()}
    found = plans.steps(claims, sets)
    cur.execute("""select subject, change_set::text, object_value->>'@value' from api.claims
                   where predicate = %s and subject = any(%s) and status <> 'deprecated'""",
                (LABEL, sorted({s["plan"] for s in found})))
    labels = {(subject, cs): text for subject, cs, text in cur.fetchall()}
    cur.execute("""select outputs->>'system', outputs->>'applied', outputs->>'decided_at' from kernel.run
                   where agent = kernel.my_agent() and status = 'succeeded' and outputs ? 'applied' order by ended_at""")
    last, floor = {}, {}
    for system, sha, at in cur.fetchall():
        last[system] = sha
        if at:
            when = datetime.fromisoformat(at)
            floor[system] = max(floor.get(system, when), when)
    return {"steps": found, "labels": labels, "last": last, "floor": floor}


def content_of(intent: Path, system: str, sha: str | None) -> bytes | None:
    """A file this runtime ran, by content: the first version of the system's file in the history whose sha256 is
    `sha` (the content is checked by its hash, so the history may be anyone's)."""
    if not sha:
        return None
    log = subprocess.run(["git", "-C", str(intent), "log", "--format=%H", "HEAD", "--", f"systems/{system}/compose.yaml"],
                         capture_output=True, text=True)
    for commit in log.stdout.split():
        out = subprocess.run(["git", "-C", str(intent), "show", f"{commit}:./systems/{system}/compose.yaml"], capture_output=True)
        if out.returncode == 0 and hashlib.sha256(out.stdout).hexdigest() == sha:
            return out.stdout
    return None


class System:
    """One managed system: apply its committed file when it changes and is approved, say each event once. A file
    whose apply failed is tried again after RETRY_SECONDS, or at once when HEAD changes it."""

    def __init__(self, intent: Path, name: str, project: str, say):
        self.intent, self.name, self.project = intent, name, project
        self.say = lambda **e: say(system=name, **e)
        self.applied, self.said, self.failed_at = None, None, 0.0

    def refuse(self, digest: str, why: str) -> None:
        if self.said != f"refused:{digest}:{why}":
            self.say(event="refused", intent=digest, reason=why)
            self.said = f"refused:{digest}:{why}"

    def step(self, cur, record: dict) -> None:
        text = committed(self.intent, self.name)
        sha = hashlib.sha256(text).hexdigest() if text is not None else None
        digest = sha[:16] if sha else None
        if text is None:
            if self.said != "unmanaged":
                self.say(event="unmanaged", reason="no compose file at HEAD: the system is left as it runs")
                self.said = "unmanaged"
            return
        if digest == self.applied:
            return
        why = refusal(text.decode("utf-8", "replace"))
        if why:
            return self.refuse(digest, why)
        base = content_of(self.intent, self.name, record["last"].get(self.name))
        approved = plans.approval(record["steps"], record["labels"], ACTIONS, self.name, text, base)
        if approved is None:
            return self.refuse(digest, "no approved plan step authorises this file: it was not approved as it is")
        if approved["decided_at"] < record["floor"].get(self.name, approved["decided_at"]):
            return self.refuse(digest, "a file approved later has run already: going back to this one needs a new approval")
        if self.said == f"failed:{digest}" and time.monotonic() - self.failed_at < RETRY_SECONDS:
            return
        error = None
        try:
            with run(cur, MODULE, {"system": self.name, "project": self.project}, plan_step=approved["step"],
                     used=approved["claims"]) as (_, outputs):
                try:
                    out = apply(self.project, text)
                    if out.returncode:
                        error = (out.stderr or out.stdout).strip()[-300:]
                except (subprocess.SubprocessError, OSError) as e:      # a hung `up --wait`, no docker: this system only
                    error = str(e)[-300:]
                outputs.update(system=self.name, decided_at=approved["decided_at"].isoformat(),
                               **({"error": error} if error else {"applied": sha}))
                if error:
                    raise RuntimeError(error)
        except RuntimeError:
            pass
        if error is None:
            self.say(event="started" if self.applied is None else "updated", intent=digest, project=self.project)
            self.applied, self.said = digest, None
        else:
            if self.said != f"failed:{digest}":
                self.say(event="failed", intent=digest, error=error)
            self.said, self.failed_at = f"failed:{digest}", time.monotonic()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run managed systems as their committed, approved compose files say.")
    ap.add_argument("--intent", default=os.environ.get("KK_INTENT_DIR"))
    which = ap.add_mutually_exclusive_group(required=True)
    which.add_argument("--system", help="one system")
    which.add_argument("--all", action="store_true",
                       help="every system under systems/ at HEAD, each as project kk-<system>, one committed later included")
    ap.add_argument("--project", help="the compose project name (with --system; default kk-<system>)")
    a = ap.parse_args(argv)
    if not a.intent:
        ap.error("--intent (or KK_INTENT_DIR)")
    if not os.environ.get("DATABASE_URL"):
        ap.error("DATABASE_URL: the runtime reads plan steps and people's decisions from the record (T26)")
    if a.system is not None and not NAME.fullmatch(a.system):
        ap.error("--system: a lower-case name")
    if a.all and a.project:
        ap.error("--project goes with --system")
    project = a.project or (f"kk-{a.system}" if a.system is not None else None)
    if project and not NAME.fullmatch(project):
        ap.error("--project: a lower-case name")
    intent = Path(a.intent).resolve()
    every = float(os.environ.get("KK_RECONCILE_SECONDS", "2"))
    say = lambda **e: print(json.dumps({"t": round(time.time(), 3), **e}), flush=True)  # noqa: E731

    def terminate(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    managed: dict[str, System] = {}
    once = os.environ.get("KK_ONCE") == "1"
    role = os.environ.get("KK_ROLE", "kkm_runtime_compose")
    conn, unreachable = None, False
    try:
        while True:
            try:
                conn = conn if conn is not None and not conn.closed else connect(role)
                with conn.cursor() as cur:
                    record = approvals(cur)
                    unreachable = False
                    names = (set(systems(intent)) | {n for n in record["last"] if NAME.fullmatch(n)}) if a.all else [a.system]
                    for name in sorted(set(names) | set(managed)):     # one gone from HEAD says so, and is left running
                        if name not in managed:
                            managed[name] = System(intent, name, project or f"kk-{name}", say)
                        managed[name].step(cur, record)
            except psycopg.Error as e:                    # without the record nothing new runs; what runs stays
                if not unreachable:
                    say(event="record-unreachable", error=str(e).strip()[-300:])
                unreachable, conn = True, None
                if once:
                    return 1
            if once:
                break
            time.sleep(every)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
