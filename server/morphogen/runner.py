"""Run a command for the judge: in a networkless container when Docker works, else directly."""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

_DOCKER_OK: bool | None = None


def docker_available() -> bool:
    global _DOCKER_OK
    if _DOCKER_OK is None:
        if not shutil.which("docker"):
            _DOCKER_OK = False
        else:
            try:
                r = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
                _DOCKER_OK = r.returncode == 0
            except (subprocess.TimeoutExpired, OSError):
                _DOCKER_OK = False
    return _DOCKER_OK


def sandbox_mode(cfg: dict) -> str:
    want = cfg.get("sandbox", "auto")
    if want == "none":
        return "none"
    if want == "docker":
        if not docker_available():
            raise RuntimeError("sandbox is set to docker, but Docker is not available")
        return "docker"
    return "docker" if docker_available() else "none"


@dataclass
class Result:
    rc: int
    out: str
    err: str
    seconds: float


def run(cmd: str, cwd: Path, cfg: dict, *, stdin: str | None = None, env: dict | None = None,
        timeout: int = 300) -> Result:
    mode = sandbox_mode(cfg)
    env = {"PYTHONDONTWRITEBYTECODE": "1", **(env or {})}
    if mode == "docker":
        args = ["docker", "run", "--rm", "-i", "--network", "none", "--memory", "1g", "--cpus", "1",
                "-v", f"{cwd}:/w:ro", "-w", "/w"]
        for k, v in env.items():
            args += ["-e", f"{k}={v}"]
        args += [cfg.get("sandbox_image", "python:3.12-slim"), "sh", "-c", cmd]
        full_env = None
    else:
        import os
        args = ["sh", "-c", cmd]
        full_env = {**os.environ, **env}
    t0 = time.perf_counter()
    try:
        p = subprocess.run(args, cwd=cwd, input=stdin, capture_output=True, text=True,
                           timeout=timeout, env=full_env)
        return Result(p.returncode, p.stdout, p.stderr, time.perf_counter() - t0)
    except subprocess.TimeoutExpired:
        return Result(124, "", f"timed out after {timeout}s", time.perf_counter() - t0)
