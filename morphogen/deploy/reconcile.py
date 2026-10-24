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
morphogen/modules/<name> in the repository, or a candidate's experiments/<id>/<name> in intent, which the
intent actuator points to when a person approves a replacement), and its environment sets only KK_* settings other than KK_ROLE: a provider's
identity and database login come from this process, not from intent.

Logins (R5-22): the file's name names the slot's reviewed provider (environments/<env>/anomaly.yaml:
morphogen/modules/anomaly or kernel/providers/anomaly). When that provider declares a login of its own
(provider.yaml `role`, `login`), the service runs as that login with none of this process's other
credentials (morphogen.logins); otherwise it gets this process's environment. Either way it never gets
KK_OTLP_SECRET: with it set, each service gets its own telemetry token, for its own name. A candidate from an
experiment runs only as the incumbent's own login, and only while its directory matches HEAD (the code
the person approved, measured and committed). It also runs as an OS user leased for it alone (KK_RUN_AS;
morphogen.confine, R5-24), from a copy of that directory (regular files only) it may read but not write,
with a home of its own, and not at all while the cluster lets any login in without its password (checked
through DATABASE_URL, which must be a superuser's to read pg_hba_file_rules); when it stops or exits,
every process of that user is ended and the user is given back. Running candidates needs CAP_SETUID and
CAP_SETGID (root).
"""
from __future__ import annotations

import argparse
import contextlib
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from morphogen import confine  # noqa: E402
from morphogen.logins import login_env, login_of, telemetry_token, undumpable  # noqa: E402


SERVICE = re.compile(r"python3 -m [a-z_][a-z0-9_]*")
CWD = re.compile(r"(kernel/providers|morphogen/modules)/[a-z0-9][a-z0-9-]*|experiments/x[0-9a-f]{12}/[a-z0-9][a-z0-9-]*")
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
            out[spec.get("provider", name.removesuffix(".yaml"))] = (hashlib.sha256(text).hexdigest()[:16],
                                                                     {**spec, "_file": name.removesuffix(".yaml")})
    return out, refused


def start(repo: Path, spec: dict, intent: Path | None = None) -> subprocess.Popen:
    experiment = intent is not None and spec["cwd"].startswith("experiments/")
    cwd = (intent if experiment else repo) / spec["cwd"]
    slot_file = spec.get("_file") or spec.get("provider", "")
    reviewed = next((d for d in (repo / "morphogen" / "modules" / slot_file, repo / "kernel" / "providers" / slot_file)
                     if (d / "provider.yaml").exists()), None)
    login = login_of(reviewed) if reviewed else None
    if experiment:
        if login is None:
            raise OSError(f"a candidate runs only as the incumbent's own login; {slot_file} declares none")
        git = lambda *a: subprocess.run(["git", "-C", str(intent), *a], capture_output=True, text=True).stdout
        if not git("ls-tree", "HEAD", "--", spec["cwd"]) or git("status", "--porcelain", "--untracked-files=all", "--", spec["cwd"]):
            raise OSError(f"{spec['cwd']} differs from HEAD: only committed experiment code runs")
        confine.pool()
    path = os.pathsep.join(filter(None, [str(cwd), str(repo / "kernel" / "src"), str(repo / "morphogen" / "src"),
                                         os.environ.get("PYTHONPATH")]))
    # OTEL_*HEADERS are not passed on: the service's own token below is the only one it holds.
    extra = {**{k: v for k, v in os.environ.items() if k.startswith("OTEL_") and not k.endswith("HEADERS")},
             **{k: str(v) for k, v in (spec.get("env") or {}).items()}, "PYTHONPATH": path,
             "PYTHONDONTWRITEBYTECODE": "1", "OTEL_SERVICE_NAME": spec.get("provider") or spec.get("_file", "")}
    if os.environ.get("KK_OTLP_SECRET"):
        extra["OTEL_EXPORTER_OTLP_HEADERS"] = f"Authorization=Bearer%20{telemetry_token(os.environ['KK_OTLP_SECRET'], extra['OTEL_SERVICE_NAME'])}"
    env = login_env(os.environ["DATABASE_URL"], *login, extra) if login else {**os.environ, **extra}
    env.pop("KK_OTLP_SECRET", None)
    cmd = shlex.split(spec["service"])
    if cmd[0] == "python3":
        cmd[0] = sys.executable
    if not experiment:
        return subprocess.Popen(cmd, cwd=cwd, env=env)
    held = contextlib.ExitStack()                        # the leased user, the copy and the home, until release()
    try:
        run = held.enter_context(confine.lease())
        import psycopg
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as su:   # needs pg_hba_file_rules: a superuser
            confine.check_cluster(su, run, *confine.where(env["DATABASE_URL"]))
        ws = held.enter_context(confine.workspace("kk-run-code-"))
        home = held.enter_context(run.home("kk-run-home-"))
        code = ws / cwd.name
        confine.copy_tree(cwd, code, skip=("__pycache__", "runs"))
        env = {**env, "HOME": str(home), "TMPDIR": str(home),
               "PYTHONPATH": env["PYTHONPATH"].replace(str(cwd), str(code), 1)}
        p = run.popen(cmd, env, cwd=code)
    except BaseException:
        held.close()
        raise
    p.confined = held
    return p


def release(p: subprocess.Popen) -> None:
    """After a confined service ends: end every process of its run user, remove its copy and home, give the
    user back."""
    if getattr(p, "confined", None):
        p.confined.close()
        p.confined = None


def stop(p: subprocess.Popen) -> None:
    p.terminate()
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
    release(p)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the services an environment's intent describes.")
    ap.add_argument("--intent", required=True)
    ap.add_argument("--env", default="sandbox")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args(argv)
    undumpable()                                         # children cannot read KK_OTLP_SECRET from /proc
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
                    release(p)
                    del running[name]
                    exited[name] = time.monotonic()
                    say(event="exited", provider=name, code=p.returncode)
            for name, (digest, spec) in want.items():
                if name not in running and time.monotonic() - exited.get(name, -backoff) >= backoff:
                    try:
                        running[name] = (digest, start(repo, spec, intent))
                    except (OSError, confine.Unconfined) as e:   # e.g. the directory is missing: say so, retry later
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
