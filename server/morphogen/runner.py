"""Runners: where the judge's commands run. A port, like the data backends.

Each runner declares capabilities so the judge and `doctor` say which
guarantees hold:

    network_isolated   the command cannot reach the network
    read_only_tree     the command cannot change the code it is judging
    resource_limits    memory and CPU are capped
    timing             'stable' when timings are comparable run to run, 'noisy' otherwise

Shipped: `none` (directly on this machine), `docker`, `podman` (rootless,
no daemon). `auto` picks Docker, then Podman, then none. Cluster runners
(Kubernetes Jobs, Nomad batch jobs) and stronger isolation (gVisor,
Firecracker) are listed in the sample catalog as planned.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

CONTAINER_CAPS = {"network_isolated": True, "read_only_tree": True, "resource_limits": True, "timing": "stable"}
RUNNERS = {
    "none": {"network_isolated": False, "read_only_tree": False, "resource_limits": False, "timing": "stable"},
    "docker": CONTAINER_CAPS,
    "podman": CONTAINER_CAPS,
}
_AVAILABLE: dict[str, bool] = {}


def available(engine: str) -> bool:
    """Whether a container engine is installed and answering."""
    if engine not in _AVAILABLE:
        ok = False
        if shutil.which(engine):
            try:
                ok = subprocess.run([engine, "info"], capture_output=True, timeout=15).returncode == 0
            except (subprocess.TimeoutExpired, OSError):
                ok = False
        _AVAILABLE[engine] = ok
    return _AVAILABLE[engine]


def docker_available() -> bool:  # kept for callers that only ask about Docker
    return available("docker")


def sandbox_mode(cfg: dict) -> str:
    want = cfg.get("sandbox", "auto")
    if want == "none":
        return "none"
    if want in ("docker", "podman"):
        if not available(want):
            raise RuntimeError(f"sandbox is set to {want}, but {want} is not available")
        return want
    if want != "auto":
        raise RuntimeError(f"unknown sandbox {want!r}; use auto, docker, podman or none")
    for engine in ("docker", "podman"):
        if available(engine):
            return engine
    return "none"


def capabilities(cfg: dict) -> dict:
    mode = sandbox_mode(cfg)
    return {"runner": mode, **RUNNERS[mode]}


@dataclass
class Result:
    rc: int
    out: str
    err: str
    seconds: float


def run(cmd: str, cwd: Path, cfg: dict, *, stdin: str | None = None, env: dict | None = None,
        timeout: int = 300, private: bool = False) -> Result:
    """Run `cmd` in `cwd`. `private`: for code under test. In a container every run is fresh
    anyway; without one, the run gets its own empty TMPDIR and HOME, removed afterwards, so
    nothing it writes there reaches the next run."""
    mode = sandbox_mode(cfg)
    env = {"PYTHONDONTWRITEBYTECODE": "1", **(env or {})}
    scratch = None
    if mode in ("docker", "podman"):
        mount = f"{cwd}:/w:ro" + (",Z" if mode == "podman" else "")  # Z: SELinux relabel for rootless Podman
        args = [mode, "run", "--rm", "-i", "--network", "none", "--memory", "1g", "--cpus", "1",
                "-v", mount, "-w", "/w"]
        for k, v in env.items():
            args += ["-e", f"{k}={v}"]
        args += [cfg.get("sandbox_image", "python:3.12-slim"), "sh", "-c", cmd]
        full_env = None
    else:
        args = ["sh", "-c", cmd]
        full_env = {**os.environ, **env}
        if private:
            scratch = Path(tempfile.mkdtemp(prefix="morphogen-run-"))
            (scratch / "tmp").mkdir()
            (scratch / "home").mkdir()
            tmp = str(scratch / "tmp")
            full_env.update({"TMPDIR": tmp, "TEMP": tmp, "TMP": tmp, "HOME": str(scratch / "home")})
    t0 = time.perf_counter()
    try:
        p = subprocess.run(args, cwd=cwd, input=stdin, capture_output=True, text=True,
                           timeout=timeout, env=full_env)
        return Result(p.returncode, p.stdout, p.stderr, time.perf_counter() - t0)
    except subprocess.TimeoutExpired:
        return Result(124, "", f"timed out after {timeout}s", time.perf_counter() - t0)
    finally:
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)
