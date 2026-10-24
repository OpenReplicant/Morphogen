"""Runs one provider's passes when the sandbox says so, so the sandbox times each pass from its own process
(R5-23). Not provider code: the sandbox's, run in the provider's process.

  python driver.py <package> <entry>

Imports `<package>.__main__`, connects with kk.lib.connect(KK_ROLE) (the login in DATABASE_URL), writes
`ready`, then for each `pass` line on stdin calls `<entry>(conn)` once and writes `done` (or `error <why>`).
The protocol has its own copy of stdout: whatever the provider prints goes to stderr.
"""
import importlib
import os
import sys

proto = os.fdopen(os.dup(1), "w", buffering=1)
os.dup2(2, 1)                                            # the provider's own prints go to stderr

from kk.lib import connect  # noqa: E402

package, entry = sys.argv[1], sys.argv[2]
one_pass = getattr(importlib.import_module(f"{package}.__main__"), entry)
conn = connect(os.environ["KK_ROLE"])
proto.write("ready\n")
for line in sys.stdin:
    if line.strip() != "pass":
        break
    try:
        one_pass(conn)
        proto.write("done\n")
    except Exception as e:                               # a failed pass is the provider's: say so and stop
        proto.write(f"error {type(e).__name__}: {str(e)[:200]}\n")
        break
