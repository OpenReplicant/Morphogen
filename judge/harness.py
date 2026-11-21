"""The harness: the base's side of one case, inside the sandbox (CLAUDE.md, rail 1: the measurer and the
measured run apart).

It runs the candidate's program as a child process, gives it the case on stdin, times it with its own
clock, and writes the one record that leaves the sandbox: exactly one line of JSON on its own stdout. The
child gets only pipes, so nothing it prints can become that record; the harness makes itself
non-dumpable, so the child (same user) can neither trace it nor open its file descriptors through
/proc. If the child kills the harness, no record is written, and the case counts as not seen, which can
only hurt the candidate.

The record:
  exit           the child's exit code (negative: killed by that signal)
  timed_out      the harness stopped it at --timeout
  wall_seconds   from just before the child starts to its exit, by the harness's monotonic clock
  cpu_seconds    the child's user + system time, as the kernel accounts it (wait4)
  output         the child's stdout (at most 1 MiB): what the base's scorer scores
  stderr_tail    the last 2000 bytes of its stderr

    python -I harness.py --work /work --module topwords --timeout 60  < case.json

A base may supply its own harness at .morphogen/harness.py (for example one that holds an environment and
talks to an agent over pipes); it must keep the same rule and write the same record.
"""

import argparse
import ctypes
import json
import os
import signal
import subprocess
import sys
import threading
import time

MAX_OUTPUT = 1 << 20
PR_SET_DUMPABLE = 4
# The program is imported from the work tree, placed after the standard library so it cannot shadow it.
BOOT = ("import sys, runpy; sys.path.append(sys.argv[1]); "
        "runpy.run_module(sys.argv[2], run_name='__main__', alter_sys=True)")


def non_dumpable():
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_DUMPABLE, 0) failed")


def _drain(pipe, buf, limit):
    while True:
        chunk = pipe.read1(65536) if hasattr(pipe, "read1") else pipe.read(65536)
        if not chunk:
            return
        if len(buf) < limit:
            buf.extend(chunk[: limit - len(buf)])


def run(work, module, payload, timeout):
    out, err = bytearray(), bytearray()
    t0 = time.monotonic()
    p = subprocess.Popen([sys.executable, "-I", "-c", BOOT, work, module], cwd=work, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True, start_new_session=True)
    readers = [threading.Thread(target=_drain, args=(p.stdout, out, MAX_OUTPUT), daemon=True),
               threading.Thread(target=_drain, args=(p.stderr, err, 1 << 16), daemon=True)]
    for r in readers:
        r.start()

    def feed():
        try:
            p.stdin.write(payload)
            p.stdin.close()
        except OSError:
            pass  # the child stopped reading; that is its business
    threading.Thread(target=feed, daemon=True).start()

    done = {}

    def reap():
        _, status, usage = os.wait4(p.pid, 0)
        done.update(status=status, usage=usage, t=time.monotonic())
    waiter = threading.Thread(target=reap, daemon=True)
    waiter.start()
    waiter.join(timeout)
    timed_out = waiter.is_alive()
    if timed_out:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        waiter.join()
    p.returncode = 0  # reaped by wait4 above; keep Popen from waiting again
    try:
        os.killpg(p.pid, signal.SIGKILL)  # whatever it left behind in its group
    except ProcessLookupError:
        pass
    for r in readers:
        r.join(0.2)  # a detached grandchild may hold the pipes open; it does not hold the record
    usage = done["usage"]
    return {"exit": os.waitstatus_to_exitcode(done["status"]), "timed_out": timed_out,
            "wall_seconds": done["t"] - t0, "cpu_seconds": usage.ru_utime + usage.ru_stime,
            "output": bytes(out).decode("utf-8", "replace"),
            "stderr_tail": bytes(err[-2000:]).decode("utf-8", "replace")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--module", required=True)
    ap.add_argument("--timeout", type=float, required=True)
    a = ap.parse_args()
    non_dumpable()
    payload = sys.stdin.buffer.read()
    rec = run(a.work, a.module, payload, a.timeout)
    line = (json.dumps(rec) + "\n").encode()
    os.write(1, line)
    os._exit(0)  # do not wait on threads still blocked on pipes a grandchild holds


if __name__ == "__main__":
    main()
