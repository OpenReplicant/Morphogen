"""Untrusted stage: run one checkout of the program on every case, each in a fresh sandbox container.

Runs inside the untrusted job, which holds no secrets and no answers. The program's code only ever
executes inside the sandbox: no network, read-only root, no capabilities, an unprivileged user, CPU,
memory and process limits, and a fresh container per case, so nothing carries over between cases or
runs. Its input arrives on stdin as JSON; whatever it writes to stdout is its output.

Inside each container the base's harness (judge/harness.py, or the base's own .morphogen/harness.py) runs
the program as a child process, times it with its own clock, and writes the one record that is scored
(CLAUDE.md, rail 1). A container that ends without a valid record leaves the case not seen. The records
this writes are the only thing that leaves the job.

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
from pathlib import Path

MAX_RECORD = 2 << 20
DEFAULT_HARNESS = Path(__file__).resolve().parent / "harness.py"
RECORD_KEYS = {"exit", "timed_out", "wall_seconds", "cpu_seconds", "output", "stderr_tail"}


def docker(*args, **kw):
    return subprocess.run(["docker", *args], capture_output=True, **kw)


def build(checkout, image, tag, harness=DEFAULT_HARNESS):
    """An image of the sandbox base with the checkout at /work and the base's harness at /harness:
    copies only, runs nothing. The root filesystem is read-only when it runs, so neither can change."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tar:
        tar.add(checkout, arcname="work", filter=lambda t: None if t.name.startswith("work/.git") else t)
        tar.add(harness, arcname="harness/harness.py")
        df = f"FROM {image}\nCOPY work /work\nCOPY harness /harness\n".encode()
        info = tarfile.TarInfo("Dockerfile")
        info.size = len(df)
        tar.addfile(info, io.BytesIO(df))
    r = docker("build", "-q", "--network", "none", "-t", tag, "-", input=buf.getvalue())
    if r.returncode:
        raise SystemExit(f"build failed: {r.stderr.decode()[-500:]}")


def parse_record(stdout):
    """The harness's one line of JSON, checked; None if there is no valid record."""
    lines = stdout[:MAX_RECORD].decode("utf-8", "replace").splitlines()
    if len(lines) != 1:
        return None
    try:
        rec = json.loads(lines[0])
    except ValueError:
        return None
    if not isinstance(rec, dict) or set(rec) != RECORD_KEYS:
        return None
    try:
        ok = (isinstance(rec["exit"], int) and isinstance(rec["timed_out"], bool)
              and float(rec["wall_seconds"]) >= 0 and float(rec["cpu_seconds"]) >= 0
              and isinstance(rec["output"], str) and isinstance(rec["stderr_tail"], str))
    except (TypeError, ValueError):
        return None
    return rec if ok else None


def run_case(tag, module, payload, limits):
    name = "mg-" + secrets.token_hex(6)
    create = docker("create", "--name", name, "--network", "none", "--read-only", "--tmpfs", "/tmp:size=16m",
                    "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "65534:65534",
                    "--cpus", str(limits["cpus"]), "--memory", limits["memory"], "--pids-limit", "64",
                    "--env", "HOME=/tmp", "-i", tag, "python", "-I", "/harness/harness.py", "--work", "/work",
                    "--module", module, "--timeout", str(limits["timeout"]))
    if create.returncode:
        raise SystemExit(f"create failed: {create.stderr.decode()[-300:]}")
    try:
        try:  # the harness keeps time; this is only a backstop against a harness that hangs
            r = docker("start", "-a", "-i", name, input=payload, timeout=limits["timeout"] + 30)
        except subprocess.TimeoutExpired:
            docker("kill", name)
            r = None
        state = json.loads(docker("inspect", name).stdout)[0]["State"]
        rec = parse_record(r.stdout) if r is not None and state["ExitCode"] == 0 else None
        if rec is None:  # no record: not seen (killed harness, out of memory, a hung container)
            return {"record": False, "container_exit": state["ExitCode"], "oom": state.get("OOMKilled", False)}
        return {**rec, "oom": state.get("OOMKilled", False)}
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
    ap.add_argument("--harness", type=Path, default=DEFAULT_HARNESS,
                    help="the base's harness (from the base checkout, never the candidate's)")
    a = ap.parse_args(argv)
    limits = {"cpus": a.cpus, "memory": a.memory, "timeout": a.timeout}
    tags = {side: f"mg-run-{side}-{secrets.token_hex(4)}" for side in SIDES}
    a.out_dir.mkdir(parents=True, exist_ok=True)
    try:
        for side in SIDES:
            build(getattr(a, side), a.image, tags[side], a.harness)
        cases = [json.loads(line) for line in a.inputs.read_text().splitlines() if line.strip()]
        with (a.out_dir / "base.jsonl").open("w") as b, (a.out_dir / "candidate.jsonl").open("w") as c:
            run_pairs(tags, a.module, cases, limits, {"base": b, "candidate": c})
    finally:
        for tag in tags.values():
            docker("rmi", "-f", tag)


if __name__ == "__main__":
    main()
