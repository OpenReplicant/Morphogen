"""Rail 1: the measurer and the measured run apart. The harness (the base's code) runs the candidate as a
child process, times it itself, and writes the only record that is scored. These run the harness
directly on the host, the same file the sandbox runs."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent.parent / "judge" / "harness.py"
# In the sandbox the harness runs unprivileged with no capabilities; root ignores the non-dumpable flag,
# so when these tests run as root they drop to the sandbox's user first.
DROP = ["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups", "--inh-caps=-all"] if os.geteuid() == 0 else []


@pytest.fixture
def tmp_path():
    d = Path(tempfile.mkdtemp(prefix="mg-harness-"))
    d.chmod(0o755)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def harness_cmd(work, timeout):
    h = work.parent / "harness.py"
    shutil.copy(HARNESS, h)
    for q in [work.parent, *work.parent.rglob("*")]:
        q.chmod(0o755 if q.is_dir() else 0o644)
    cmd = [sys.executable, "-I", str(h), "--work", str(work), "--module", "prog", "--timeout", str(timeout)]
    # The harness's stdout must be a pipe its own user owns, as in a non-root CI job: reopening a pipe
    # through /proc re-checks the pipe's owner, which would hide the cheat when the pipe is root's.
    return DROP + ["sh", "-c", 'exec "$@" | cat', "sh", *cmd]


def run(tmp_path, body, payload=b'{"x": 1}', timeout=5):
    work = tmp_path / "work"
    (work / "prog").mkdir(parents=True)
    (work / "prog" / "__main__.py").write_text(textwrap.dedent(body))
    r = subprocess.run(harness_cmd(work, timeout), input=payload, capture_output=True, timeout=timeout + 10)
    lines = r.stdout.decode().splitlines()
    assert len(lines) == 1, f"the harness writes exactly one line, got {r.stdout!r} / {r.stderr!r}"
    return json.loads(lines[0])


def test_an_honest_program(tmp_path):
    rec = run(tmp_path, "import sys, json\nprint(json.load(sys.stdin)['x'] + 1)\n")
    assert rec["exit"] == 0 and rec["output"] == "2\n" and not rec["timed_out"]
    assert 0 <= rec["wall_seconds"] < 2 and rec["cpu_seconds"] >= 0


def test_a_fake_record_on_stdout_is_only_output(tmp_path):
    fake = '{"exit": 0, "output": "42", "wall_seconds": 0.0, "cpu_seconds": 0.0, "timed_out": false}'
    rec = run(tmp_path, f"import time\nprint({fake!r})\ntime.sleep(0.5)\n")
    assert rec["output"] == fake + "\n"          # just the program's output, for the scorer
    assert rec["wall_seconds"] >= 0.45           # the harness's own clock


def test_patching_the_clock_in_its_own_process_changes_nothing(tmp_path):
    rec = run(tmp_path, """
        import time
        time.perf_counter = lambda: 0.0
        time.monotonic = lambda: 0.0
        t = time.time()
        while time.time() - t < 0.5:
            pass
    """)
    assert rec["wall_seconds"] >= 0.45 and rec["cpu_seconds"] >= 0.3


def test_it_cannot_write_to_the_harness_output_through_proc(tmp_path):
    rec = run(tmp_path, """
        import os
        for fd in ("1", "2"):
            try:
                with open(f"/proc/{os.getppid()}/fd/{fd}", "w") as f:
                    f.write('{"exit": 0, "output": "forged", "wall_seconds": 0, "cpu_seconds": 0}\\n')
                print("WROTE", fd)
            except OSError as e:
                print("blocked", fd, e.errno)
    """)
    assert "WROTE" not in rec["output"], rec["output"]


def test_a_detached_grandchild_cannot_add_lines(tmp_path):
    run(tmp_path, """
        import os, time
        if os.fork() == 0:
            os.setsid()
            time.sleep(0.3)
            print('{"exit": 0, "output": "late"}', flush=True)
            os._exit(0)
    """)  # run() asserts exactly one line


def test_a_timeout_is_the_harness_s(tmp_path):
    rec = run(tmp_path, "import time\ntime.sleep(30)\n", timeout=1)
    assert rec["timed_out"] and rec["wall_seconds"] < 3


def test_killing_the_harness_leaves_no_record(tmp_path):
    work = tmp_path / "work"
    (work / "prog").mkdir(parents=True)
    (work / "prog" / "__main__.py").write_text("import os, signal\nos.kill(os.getppid(), signal.SIGKILL)\n")
    r = subprocess.run(harness_cmd(work, 5), input=b"{}", capture_output=True, timeout=15)
    assert r.stdout == b""   # no record: the run counts the case as not seen, which can only hurt the candidate


from judge import run as runner  # noqa: E402

GOOD = {"exit": 0, "timed_out": False, "wall_seconds": 0.1, "cpu_seconds": 0.05, "output": "x", "stderr_tail": ""}


def test_the_run_accepts_one_valid_record_only():
    assert runner.parse_record((json.dumps(GOOD) + "\n").encode()) == GOOD
    for bad in [b"", b"not json\n", (json.dumps(GOOD) + "\n").encode() * 2,         # nothing, junk, two lines
                (json.dumps({**GOOD, "accuracy": 1.0}) + "\n").encode(),             # an extra field
                (json.dumps({k: v for k, v in GOOD.items() if k != "cpu_seconds"}) + "\n").encode(),
                (json.dumps({**GOOD, "wall_seconds": -1}) + "\n").encode(),          # negative time
                (json.dumps({**GOOD, "exit": "0"}) + "\n").encode()]:
        assert runner.parse_record(bad) is None, bad
