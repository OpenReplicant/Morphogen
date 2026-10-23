"""Reconcile one environment's intent: run each provider's service as its intent file says, and restart
it when the file changes. The bootstrap orchestrator for Morphogen's own stack (R5-07): the intent
actuator only commits to intent/; this is what makes the running system match.

  python3 morphogen/deploy/reconcile.py --intent morphogen/intent --env sandbox [--repo .]

Each `environments/<env>/<provider>.yaml` names the service command, its directory (relative to
--repo) and its environment, added to this process's own (DATABASE_URL, OTEL_*, ...). The directory,
kernel/src and morphogen/src are put on PYTHONPATH. A file removed stops its service; a service that
exits is started again after KK_RESTART_SECONDS (default 5). Prints one JSON line per event. Every
KK_RECONCILE_SECONDS (default 1) it re-reads.

Intent is read from the commit at HEAD, never the work tree: only what was committed (by the intent
actuator, or a person) runs, and an edit left uncommitted runs nothing. A file is refused unless its
service is `python3 -m <module>`, its directory is a provider's (kernel/providers/<name> or
morphogen/modules/<name>), and its environment sets only KK_* settings other than KK_ROLE: a provider's
identity and database login come from this process, not from intent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import yaml


SERVICE = re.compile(r"python3 -m [a-z_][a-z0-9_]*")
CWD = re.compile(r"(kernel/providers|morphogen/modules)/[a-z0-9][a-z0-9-]*")
SETTING = re.compile(r"KK_[A-Z0-9_]+")


def committed(intent: Path, env: str) -> dict[str, bytes]:
    """file name -> content of each intent file of the environment at HEAD."""
    def git(*args) -> bytes:
        return subprocess.run(["git", "-C", str(intent), *args], check=True, capture_output=True).stdout
    names = git("ls-tree", "--name-only", "HEAD", "--", f"environments/{env}/").decode().split()
    return {n.rsplit("/", 1)[-1]: git("show", f"HEAD:./{n}") for n in names if n.endswith(".yaml")}


def refusal(spec: dict):
    """Why an intent file is not run, or None."""
    if not isinstance(spec.get("service"), str) or not SERVICE.fullmatch(spec["service"]):
        return "service must be python3 -m <module>"
    if not isinstance(spec.get("cwd"), str) or not CWD.fullmatch(spec["cwd"]):
        return "cwd must be a provider's directory"
    env = spec.get("env") or {}
    if not isinstance(env, dict) or any(not SETTING.fullmatch(str(k)) or k == "KK_ROLE" for k in env):
        return "env may set only KK_* settings other than KK_ROLE"
    return None


def desired(intent: Path, env: str) -> tuple[dict[str, tuple[str, dict]], dict[str, str]]:
    """(provider -> (content hash, spec), file -> why refused) for the environment's committed intent."""
    out, refused = {}, {}
    for name, text in sorted(committed(intent, env).items()):
        spec = yaml.safe_load(text) or {}
        why = refusal(spec) if isinstance(spec, dict) else "not a mapping"
        if why:
            refused[name] = why
        else:
            out[spec.get("provider", name.removesuffix(".yaml"))] = (hashlib.sha256(text).hexdigest()[:16], spec)
    return out, refused


def start(repo: Path, spec: dict) -> subprocess.Popen:
    cwd = repo / spec.get("cwd", ".")
    path = os.pathsep.join(filter(None, [str(cwd), str(repo / "kernel" / "src"), str(repo / "morphogen" / "src"),
                                         os.environ.get("PYTHONPATH")]))
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
    backoff = float(os.environ.get("KK_RESTART_SECONDS", "5"))
    running: dict[str, tuple[str, subprocess.Popen]] = {}
    exited: dict[str, float] = {}
    said: dict[str, str] = {}
    say = lambda **e: print(json.dumps({"t": round(time.time(), 3), **e}), flush=True)

    def terminate(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)       # stopping the reconciler stops its services
    try:
        while True:
            want, refused = desired(intent, a.env)
            for name, why in refused.items():
                if said.get(name) != why:
                    say(event="refused", file=name, reason=why)
                    said[name] = why
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
                    exited[name] = time.monotonic()
                    say(event="exited", provider=name, code=p.returncode)
            for name, (digest, spec) in want.items():
                if name not in running and time.monotonic() - exited.get(name, -backoff) >= backoff:
                    try:
                        running[name] = (digest, start(repo, spec))
                    except OSError as e:          # e.g. the provider's directory is missing: say so, retry later
                        exited[name] = time.monotonic()
                        say(event="failed", provider=name, error=str(e)[:200])
                        continue
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
