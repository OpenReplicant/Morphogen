"""kk.telemetry: recorded values reach an OTLP/HTTP receiver as one delta histogram per name, and nothing
is sent or kept when no endpoint is configured. No database.

  python3 kernel/providers/tests/test_telemetry.py
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from kk.telemetry import Metrics  # noqa: E402

got = []


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        got.append((self.path, self.headers["Content-Type"], json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg)


server = HTTPServer(("127.0.0.1", 0), Receiver)
threading.Thread(target=server.serve_forever, daemon=True).start()
m = Metrics(f"http://127.0.0.1:{server.server_port}/v1/metrics", "belief-corroboration", interval=3600)
for v in (0.5, 1.5, 4.0):
    m.record("kk.feed.lag", v, "s")
m.record("kk.step.duration", 0.25, "s")
m.flush()
check(len(got) == 1 and got[0][0] == "/v1/metrics" and got[0][1] == "application/json", "one OTLP/HTTP JSON request")
rm = got[0][2]["resourceMetrics"][0]
check(rm["resource"]["attributes"] == [{"key": "service.name", "value": {"stringValue": "belief-corroboration"}}],
      "the resource names the service")
lag = next(x for x in rm["scopeMetrics"][0]["metrics"] if x["name"] == "kk.feed.lag")
p = lag["histogram"]["dataPoints"][0]
check(lag["histogram"]["aggregationTemporality"] == 1 and p["count"] == "3" and p["sum"] == 6.0
      and p["min"] == 0.5 and p["max"] == 4.0 and lag["unit"] == "s", "a delta histogram: count, sum, min, max")
m.flush()
check(len(got) == 1, "nothing recorded since the last export: nothing sent")
off = Metrics(None, "x")
off.record("kk.feed.lag", 1.0)
check(off.body() is None, "no endpoint: values are not kept")
server.shutdown()
