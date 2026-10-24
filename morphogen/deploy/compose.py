"""Reconcile a managed system (R5-25): run `docker compose up` on the system's compose file as committed in
intent, and again whenever the commit changes it. The orchestrator for systems Morphogen did not build:
the intent actuator only commits to intent/systems/<system>/compose.yaml; this makes the system match.

  python3 morphogen/deploy/compose.py --intent DIR --system NAME [--project NAME]

The file is read from the commit at HEAD, never the work tree, and refused unless it is on the allow list
(`refusal`): only `services`; per service only image (pinned by digest), command, entrypoint,
environment, ports (published on 127.0.0.1), depends_on, healthcheck, restart, labels, working_dir and
user; no `$` anywhere (compose would fill it from this process's environment). Anything else (privileged,
cap_add, devices, volumes, build, env_file, network_mode, extends, ...) is refused, and the system keeps
running as it was. The file is copied into a fresh private directory and compose runs there with only
PATH, HOME and DOCKER_HOST, so no `.env` file or variable of ours reaches it. A file removed from HEAD
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
        if extra := sorted(set(svc) - SERVICE_KEYS):
            return f"service {name}: {', '.join(extra)} not allowed"
        if not isinstance(svc.get("image"), str) or not DIGEST.fullmatch(svc["image"]):
            return f"service {name}: the image must be pinned by digest (name@sha256:...)"
        ports = svc.get("ports") or []
        if not isinstance(ports, list) or not all(isinstance(p, str) and PORT.fullmatch(p) for p in ports):
            return f"service {name}: ports must be published on 127.0.0.1 only (\"127.0.0.1:[host]:container\")"
        env = svc.get("environment") or {}
        if isinstance(env, dict):
            if not all(isinstance(v, (str, int, float, bool)) or v is None for v in env.values()):
                return f"service {name}: environment values must be plain"
        elif not isinstance(env, list) or not all(isinstance(x, str) for x in env):
            return f"service {name}: environment must be a mapping or a list of NAME=value"
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run a managed system as its committed compose file says.")
    ap.add_argument("--intent", required=True)
    ap.add_argument("--system", required=True)
    ap.add_argument("--project", help="the compose project name (default kk-<system>)")
    a = ap.parse_args(argv)
    if not NAME.fullmatch(a.system):
        ap.error("--system: a lower-case name")
    project = a.project or f"kk-{a.system}"
    if not NAME.fullmatch(project):
        ap.error("--project: a lower-case name")
    intent = Path(a.intent).resolve()
    every = float(os.environ.get("KK_RECONCILE_SECONDS", "2"))
    say = lambda **e: print(json.dumps({"t": round(time.time(), 3), "system": a.system, **e}), flush=True)

    def terminate(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    applied, said = None, None
    try:
        while True:
            text = committed(intent, a.system)
            digest = hashlib.sha256(text).hexdigest()[:16] if text is not None else None
            if text is None:
                if said != "unmanaged":
                    say(event="unmanaged", reason="no compose file at HEAD: the system is left as it runs")
                    said = "unmanaged"
            elif digest != applied:
                why = refusal(text.decode("utf-8", "replace"))
                if why:
                    if said != f"refused:{digest}":
                        say(event="refused", intent=digest, reason=why)
                        said = f"refused:{digest}"
                else:
                    out = apply(project, text)
                    if out.returncode == 0:
                        say(event="started" if applied is None else "updated", intent=digest, project=project)
                        applied, said = digest, None
                    elif said != f"failed:{digest}":
                        say(event="failed", intent=digest, error=(out.stderr or out.stdout).strip()[-300:])
                        said = f"failed:{digest}"
            time.sleep(every)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
