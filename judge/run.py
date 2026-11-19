"""Untrusted stage: run one checkout of the program on every case, each in a fresh sandbox container.

Runs inside the untrusted job, which holds no secrets and no answers. The program's code only ever
executes inside the sandbox: no network, read-only root, no capabilities, an unprivileged user, CPU,
memory and process limits, and a fresh container per case, so nothing carries over between cases or
runs. Its input arrives on stdin as JSON; whatever it writes to stdout is its output.

Wall time is the Docker daemon's own record of when the container started and stopped, not anything
the program measures. The records this writes are the only thing that leaves the job.

Base and candidate run as pairs: for each case, both run back to back, in an order chosen by a coin
flip. Running all of one side and then all of the other turns any drift in the machine's load into a
difference between the sides, and identical code then "passes" as faster (measured: DECISIONS.md).

    python -m judge.run --base DIR --candidate DIR --inputs inputs.jsonl --image IMAGE --out-dir OUT
"""

import argparse
import io
import json
import secrets
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path

MAX_OUTPUT = 1 << 20
# The program is imported from /work, placed after the standard library so it cannot shadow it.
# -I: ignore PYTHON* variables and the user site; the script's directory is not on sys.path.
BOOT = ("import sys, runpy; sys.path.append('/work'); "
        "runpy.run_module(sys.argv[1], run_name='__main__', alter_sys=True)")


def docker(*args, **kw):
    return subprocess.run(["docker", *args], capture_output=True, **kw)


def build(checkout, image, tag):
    """An image of the sandbox base with the checkout copied to /work: copies only, runs nothing."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tar:
        tar.add(checkout, arcname="work", filter=lambda t: None if t.name.startswith("work/.git") else t)
        df = f"FROM {image}\nCOPY work /work\n".encode()
        info = tarfile.TarInfo("Dockerfile")
        info.size = len(df)
        tar.addfile(info, io.BytesIO(df))
    r = docker("build", "-q", "--network", "none", "-t", tag, "-", input=buf.getvalue())
    if r.returncode:
        raise SystemExit(f"build failed: {r.stderr.decode()[-500:]}")


def _time(s):
    # Docker gives nanoseconds; Python parses microseconds.
    head, _, frac = s.rstrip("Z").partition(".")
    return datetime.fromisoformat(head).timestamp() + float("0." + (frac or "0"))


def run_case(tag, module, payload, limits):
    name = "mg-" + secrets.token_hex(6)
    create = docker("create", "--name", name, "--network", "none", "--read-only", "--tmpfs", "/tmp:size=16m",
                    "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "65534:65534",
                    "--cpus", str(limits["cpus"]), "--memory", limits["memory"], "--pids-limit", "64",
                    "--env", "HOME=/tmp", "-i", tag, "python", "-I", "-c", BOOT, module)
    if create.returncode:
        raise SystemExit(f"create failed: {create.stderr.decode()[-300:]}")
    try:
        try:
            r = docker("start", "-a", "-i", name, input=payload, timeout=limits["timeout"])
            timed_out = False
        except subprocess.TimeoutExpired:
            docker("kill", name)
            r, timed_out = None, True
        state = json.loads(docker("inspect", name).stdout)[0]["State"]
        wall = _time(state["FinishedAt"]) - _time(state["StartedAt"])
        out = (r.stdout if r else b"")[:MAX_OUTPUT].decode("utf-8", "replace")
        err = (r.stderr if r else b"")[-2000:].decode("utf-8", "replace")
        return {"exit": state["ExitCode"], "oom": state.get("OOMKilled", False), "timed_out": timed_out,
                "wall_seconds": wall, "output": out, "stderr_tail": err}
    finally:
        docker("rm", "-f", name)


SIDES = ("base", "candidate")


def run_pairs(tags, module, cases, limits, out, order=None):
    """Run each case on both sides back to back, the order inside each pair by coin flip.
    tags: {side: image tag}; out: {side: open file}. order(case) -> sides, for tests."""
    coin = secrets.SystemRandom()
    for case in cases:
        sides = order(case) if order else (SIDES if coin.random() < 0.5 else SIDES[::-1])
        payload = json.dumps(case["input"]).encode()
        for side in sides:
            rec = run_case(tags[side], module, payload, limits)
            out[side].write(json.dumps({"id": case["id"], **rec, "ran_first": side == sides[0]}) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, type=Path)
    ap.add_argument("--candidate", required=True, type=Path)
    ap.add_argument("--inputs", required=True, type=Path)
    ap.add_argument("--image", required=True)
    ap.add_argument("--module", required=True)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--cpus", default="1")
    ap.add_argument("--memory", default="512m")
    ap.add_argument("--timeout", type=float, default=60)
    a = ap.parse_args(argv)
    limits = {"cpus": a.cpus, "memory": a.memory, "timeout": a.timeout}
    tags = {side: f"mg-run-{side}-{secrets.token_hex(4)}" for side in SIDES}
    a.out_dir.mkdir(parents=True, exist_ok=True)
    try:
        for side in SIDES:
            build(getattr(a, side), a.image, tags[side])
        cases = [json.loads(line) for line in a.inputs.read_text().splitlines() if line.strip()]
        with (a.out_dir / "base.jsonl").open("w") as b, (a.out_dir / "candidate.jsonl").open("w") as c:
            run_pairs(tags, a.module, cases, limits, {"base": b, "candidate": c})
    finally:
        for tag in tags.values():
            docker("rmi", "-f", tag)


if __name__ == "__main__":
    main()
