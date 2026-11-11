"""A model gateway for the metered-runs tests (PLAN.md 7c): a fake one in a container on its own bridge network,
which answers calls that carry a key it knows and logs each (time, key, tokens), and a meter outside the
repository that reads that log, as an operator's meter reads their gateway's own record."""

import json
import os
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

ENGINE = os.environ.get("MORPHOGEN_TEST_SANDBOX", "none")
KEY = "judge-key-0123456789abcdef"

SERVER = r'''
import json, os, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
KEYS = set(os.environ["GW_KEYS"].split(","))
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        key = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
        if key not in KEYS:
            self.send_response(401); self.end_headers(); return
        with open("/tmp/calls.log", "a") as f:
            f.write(json.dumps({"ts": time.time(), "key": key, "tokens": 10}) + "\n")
        body = json.dumps({"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 10}}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)
ThreadingHTTPServer(("0.0.0.0", 8080), H).serve_forever()
'''

METER = r'''
import json, subprocess, sys, time
from pathlib import Path
engine, container, key, state, op, run_id = sys.argv[1:7]
f = Path(state) / run_id
if op == "open":
    f.write_text(str(time.time()))
    print(json.dumps({"env": {"GW_KEY": key}}))
else:
    start = float(f.read_text())
    log = subprocess.run([engine, "exec", container, "sh", "-c", "cat /tmp/calls.log 2>/dev/null"],
                         capture_output=True, text=True).stdout
    calls = [json.loads(l) for l in log.splitlines() if l.strip()]
    mine = [c for c in calls if c["key"] == key and c["ts"] >= start]
    print(json.dumps({"calls": len(mine), "tokens": sum(c["tokens"] for c in mine)}))
'''

# what a candidate imports to call a model through the gateway it was given
CALL = '''import json as _j, os as _o, urllib.request as _u
def call(key=None):
    req = _u.Request(_o.environ["MORPHOGEN_GATEWAY"] + "/v1/chat/completions", _j.dumps({"model": "m"}).encode(),
                     {"Authorization": "Bearer " + (key or _o.environ["GW_KEY"]), "Content-Type": "application/json"})
    return _j.loads(_u.urlopen(req, timeout=10).read())
'''


class FakeGateway:
    """The gateway container (on a bridge network of its own, as compose would put it) and the meter."""

    def __init__(self):
        tag = "morphogen-test-gw-" + secrets.token_hex(4)
        self.container, self.net = tag, tag + "-out"
        self.dir = Path(tempfile.mkdtemp(prefix="morphogen-meter-"))
        (self.dir / "state").mkdir()
        (self.dir / "meter.py").write_text(METER)
        subprocess.run([ENGINE, "network", "create", self.net], check=True, capture_output=True)
        subprocess.run([ENGINE, "run", "-d", "--rm", "--name", self.container, "--network", self.net,
                        "-e", f"GW_KEYS={KEY}", "docker.io/library/python:3.12-slim", "python", "-c", SERVER],
                       check=True, capture_output=True)

    def local(self) -> dict:
        meter = f"python3 {self.dir / 'meter.py'} {ENGINE} {self.container} {KEY} {self.dir / 'state'}"
        return {"gateway": {"container": self.container, "port": 8080, "meter": meter}}

    def close(self):
        subprocess.run([ENGINE, "rm", "-f", "-t", "0", self.container], capture_output=True)
        subprocess.run([ENGINE, "network", "rm", "-f", self.net], capture_output=True)
        shutil.rmtree(self.dir, ignore_errors=True)
