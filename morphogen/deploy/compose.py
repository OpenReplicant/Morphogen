"""Reconcile a managed system (R5-25): run `docker compose up` on the system's compose file as committed in
intent, and again whenever the commit changes it. The orchestrator for systems Morphogen did not build:
the intent actuator only commits to intent/systems/<system>/compose.yaml; this makes the system match.

  python3 morphogen/deploy/compose.py --intent DIR --system NAME [--project NAME]
  python3 morphogen/deploy/compose.py --intent DIR --all        every system at HEAD, as project kk-<system>

With --all, a system committed later (a described system the intent actuator wrote once a person approved its
file, R5-29) starts without anyone starting a runner for it: the design loop ends with the system running. A
commit under systems/ is the approval: point --all at an intent repository only the intent actuator and people
commit to (morphogen/deploy/local.py keeps its own). One system's failure (a refused file, an `up` that fails or
hangs past its timeout) is that system's event; the others carry on.

The file is read from the commit at HEAD, never the work tree, and refused unless it is on the allow list
(`refusal`): only `services`; per service only image (pinned by digest), command, entrypoint,
environment, ports (published on 127.0.0.1), depends_on, healthcheck, restart, labels, working_dir and
user; no `$` anywhere (compose would fill it from this process's environment). Anything else (privileged,
cap_add, devices, volumes, build, env_file, network_mode, extends, ...) is refused, and the system keeps
running as it was. The file is copied into a fresh private directory and compose runs there with only
PATH, HOME and DOCKER_HOST, so no `.env` file or variable of ours reaches it (an environment entry
without a value, which would pass one on, is refused). A file removed from HEAD
leaves the system running (it is someone else's: stopping it is a person's call) and says so.
Prints one JSON line per event. Every KK_RECONCILE_SECONDS (default 2) it re-reads. Needs Docker.
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
from pathlib import Path

import yaml

NAME = re.compile(r"[a-z0-9][a-z0-9_.-]*")
SERVICE_KEYS = {"image", "command", "entrypoint", "environment", "ports", "depends_on", "healthcheck", "restart",
                "labels", "working_dir", "user"}
DIGEST = re.compile(r"[^\s@]+@sha256:[0-9a-f]{64}")
RETRY_SECONDS = float(os.environ.get("KK_COMPOSE_RETRY_SECONDS", "60"))
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


class System:
    """One managed system: apply its committed file when it changes, say each event once. A file whose apply
    failed is tried again after RETRY_SECONDS, or at once when HEAD changes it."""

    def __init__(self, intent: Path, name: str, project: str, say):
        self.intent, self.name, self.project = intent, name, project
        self.say = lambda **e: say(system=name, **e)
        self.applied, self.said, self.failed_at = None, None, 0.0

    def step(self) -> None:
        text = committed(self.intent, self.name)
        digest = hashlib.sha256(text).hexdigest()[:16] if text is not None else None
        if text is None:
            if self.said != "unmanaged":
                self.say(event="unmanaged", reason="no compose file at HEAD: the system is left as it runs")
                self.said = "unmanaged"
        elif digest != self.applied:
            why = refusal(text.decode("utf-8", "replace"))
            if why:
                if self.said != f"refused:{digest}":
                    self.say(event="refused", intent=digest, reason=why)
                    self.said = f"refused:{digest}"
            elif self.said != f"failed:{digest}" or time.monotonic() - self.failed_at >= RETRY_SECONDS:
                try:
                    out = apply(self.project, text)
                    ok, error = out.returncode == 0, (out.stderr or out.stdout).strip()[-300:]
                except (subprocess.SubprocessError, OSError) as e:      # a hung `up --wait`, no docker: this system only
                    ok, error = False, str(e)[-300:]
                if ok:
                    self.say(event="started" if self.applied is None else "updated", intent=digest, project=self.project)
                    self.applied, self.said = digest, None
                else:
                    if self.said != f"failed:{digest}":
                        self.say(event="failed", intent=digest, error=error)
                    self.said, self.failed_at = f"failed:{digest}", time.monotonic()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run managed systems as their committed compose files say.")
    ap.add_argument("--intent", required=True)
    which = ap.add_mutually_exclusive_group(required=True)
    which.add_argument("--system", help="one system")
    which.add_argument("--all", action="store_true",
                       help="every system under systems/ at HEAD, each as project kk-<system>, one committed later included")
    ap.add_argument("--project", help="the compose project name (with --system; default kk-<system>)")
    a = ap.parse_args(argv)
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
    try:
        while True:
            names = systems(intent) if a.all else [a.system]
            for name in sorted(set(names) | set(managed)):     # one gone from HEAD says so, and is left running
                if name not in managed:
                    managed[name] = System(intent, name, project or f"kk-{name}", say)
                managed[name].step()
            time.sleep(every)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
