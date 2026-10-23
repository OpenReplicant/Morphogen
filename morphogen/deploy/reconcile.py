"""Reconcile one environment's intent: run each provider's service as its intent file says, and restart
it when the file changes. The bootstrap orchestrator for Morphogen's own stack (R5-07): the intent
actuator only commits to intent/; this is what makes the running system match.

  python3 morphogen/deploy/reconcile.py --intent morphogen/intent --env sandbox [--repo .]

Each `environments/<env>/<provider>.yaml` names the service command, its directory (relative to
--repo) and its environment, added to this process's own (DATABASE_URL, OTEL_*, ...). The directory and
kernel/src are put on PYTHONPATH. A file removed stops its service; a service that exits is started again
at the next check. Prints one JSON line per event. Every KK_RECONCILE_SECONDS (default 1) it re-reads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import yaml


def desired(intent: Path, env: str) -> dict[str, tuple[str, dict]]:
    """provider -> (content hash, spec) for every intent file of the environment."""
    out = {}
    for f in sorted((intent / "environments" / env).glob("*.yaml")):
        text = f.read_bytes()
        spec = yaml.safe_load(text) or {}
        if spec.get("service"):
            out[spec.get("provider", f.stem)] = (hashlib.sha256(text).hexdigest()[:16], spec)
    return out


def start(repo: Path, spec: dict) -> subprocess.Popen:
    cwd = repo / spec.get("cwd", ".")
    path = os.pathsep.join(filter(None, [str(cwd), str(repo / "kernel" / "src"), os.environ.get("PYTHONPATH")]))
    env = {**os.environ, **{k: str(v) for k, v in (spec.get("env") or {}).items()}, "PYTHONPATH": path,
           "OTEL_SERVICE_NAME": spec.get("provider", "")}
    cmd = shlex.split(spec["service"])
    if cmd[0] == "python3":
        cmd[0] = sys.executable
    return subprocess.Popen(cmd, cwd=cwd, env=env)


def stop(p: subprocess.Popen) -> None:
    p.terminate()
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the services an environment's intent describes.")
    ap.add_argument("--intent", required=True)
    ap.add_argument("--env", default="sandbox")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args(argv)
    intent, repo = Path(a.intent).resolve(), Path(a.repo).resolve()
    every = float(os.environ.get("KK_RECONCILE_SECONDS", "1"))
    running: dict[str, tuple[str, subprocess.Popen]] = {}
    say = lambda **e: print(json.dumps({"t": round(time.time(), 3), **e}), flush=True)

    def terminate(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)       # stopping the reconciler stops its services
    try:
        while True:
            want = desired(intent, a.env)
            for name in list(running):
                digest, p = running[name]
                if name not in want:
                    stop(p)
                    del running[name]
                    say(event="stopped", provider=name)
                elif want[name][0] != digest:
                    stop(p)
                    del running[name]
                    say(event="restarting", provider=name, intent=want[name][0])
                elif p.poll() is not None:
                    del running[name]
                    say(event="exited", provider=name, code=p.returncode)
            for name, (digest, spec) in want.items():
                if name not in running:
                    running[name] = (digest, start(repo, spec))
                    say(event="started", provider=name, intent=digest, env=spec.get("env") or {})
            time.sleep(every)
    except KeyboardInterrupt:
        pass
    finally:
        for _, p in running.values():
            stop(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
