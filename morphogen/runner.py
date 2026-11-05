"""Runners: where the judge's commands run, and which guarantees hold there.

Each runner declares the guarantees it provides; a cell may require some (`requires:` in
morphogen.yaml), and the judge refuses to score it on a runner that lacks them rather than quietly
giving weaker evidence. Every verdict records the guarantees that held.

    network_isolated      the command cannot reach the network
    read_only_tree        the command cannot change the code it is judged on
    private_paths_hidden  only the candidate's tree is visible: not the scorer's private answers,
                          not the rest of the machine
    fresh_state           nothing a run writes survives into the next run
    resource_limits       memory and CPU are capped
    timing                'stable' when timings are comparable run to run, 'noisy' otherwise

Shipped: `podman` (the default: rootless, no daemon), `docker` (the same container path, for
machines that have Docker), and `none` (directly on this machine, with a private TMPDIR and HOME
per run, which is not isolation). `auto` picks Podman, then Docker, then none.

Future runners, not built: bubblewrap (unprivileged Linux namespaces, no images, the host's own
interpreter and packages; what Claude Code's Linux sandbox uses), gVisor (a user-space kernel),
Firecracker (micro-VMs), macOS's sandbox, and remote runners (a CI job, a Kubernetes Job).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

GUARANTEES = ("network_isolated", "read_only_tree", "private_paths_hidden", "fresh_state", "resource_limits")
CONTAINER_CAPS = {**{g: True for g in GUARANTEES}, "timing": "stable"}
RUNNERS = {
    "none": {**{g: False for g in GUARANTEES}, "timing": "stable"},
    "podman": CONTAINER_CAPS,
    "docker": CONTAINER_CAPS,
}
ENGINES = ("podman", "docker")  # auto's order
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


def sandbox_mode(cfg: dict) -> str:
    want = cfg.get("sandbox", "auto")
    if want == "none":
        return "none"
    if want in ENGINES:
        if not available(want):
            raise RuntimeError(f"sandbox is set to {want}, but {want} is not available")
        return want
    if want != "auto":
        raise RuntimeError(f"unknown sandbox {want!r}; use auto, podman, docker or none")
    for engine in ENGINES:
        if available(engine):
            return engine
    return "none"


def capabilities(cfg: dict) -> dict:
    mode = sandbox_mode(cfg)
    return {"runner": mode, **RUNNERS[mode]}


def missing(cfg: dict, required: list[str]) -> list[str]:
    """The required guarantees this project's runner does not provide."""
    caps = capabilities(cfg)
    return [g for g in required if not caps.get(g)]


@dataclass
class Result:
    rc: int
    out: str
    err: str
    seconds: float


_ROOTS: dict[str, Path] = {}


def tree_root(cwd: Path) -> Path:
    """The top of the git worktree holding `cwd` (the candidate's or the base's whole tree), or `cwd`
    itself outside git. Containers mount this tree, so a target can use code shared with the rest of
    its repository; the scorer's private answers live outside it and stay hidden."""
    key = str(Path(cwd).resolve())
    if key not in _ROOTS:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True)
        _ROOTS[key] = Path(r.stdout.strip()).resolve() if r.returncode == 0 and r.stdout.strip() else Path(key)
    return _ROOTS[key]


def run(cmd: str, cwd: Path, cfg: dict, *, stdin: str | None = None, env: dict | None = None,
        timeout: int = 300, private: bool = False) -> Result:
    """Run `cmd` in `cwd`. `private`: for code under test. In a container every run is fresh
    anyway; without one, the run gets its own empty TMPDIR and HOME, removed afterwards, so
    nothing it writes there reaches the next run."""
    mode = sandbox_mode(cfg)
    env = {"PYTHONDONTWRITEBYTECODE": "1", **(env or {})}
    scratch = None
    if mode in ("docker", "podman"):
        root = tree_root(cwd)
        inner = Path("/w") / Path(cwd).resolve().relative_to(root)
        mount = f"{root}:/w:ro" + (",Z" if mode == "podman" else "")  # Z: SELinux relabel for rootless Podman
        args = [mode, "run", "--rm", "-i", "--network", "none", "--memory", "1g", "--cpus", "1",
                "-v", mount, "-w", str(inner)]
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
