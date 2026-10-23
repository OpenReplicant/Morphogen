"""OpenTelemetry observer: an OTLP/HTTP receiver (POST /v1/metrics, JSON or protobuf) that records, once
per window, each mapped metric's mean per resource as an observation (observe.py).

  python -m observer_otel [--port 4318]

Each window (KK_WINDOW_SECONDS, default 60, aligned to the clock) gives one change set, keyed by the
receiver and the window end, so a restart never records a window twice; points arriving after their
window was recorded are dropped. Providers send to it with the standard OpenTelemetry variables
(OTEL_EXPORTER_OTLP_ENDPOINT=http://<host>:<port>; kk.telemetry, or any OpenTelemetry SDK).
Env: DATABASE_URL (a login that may SET ROLE to KK_ROLE), KK_ROLE (default kkm_observer_otel),
KK_WINDOW_SECONDS, KK_OTLP_PORT (default 4318), KK_OTLP_SOURCE (the receiver's URL as cited; default
http://<hostname>:<port>/v1/metrics).
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from kk.lib import connect, run, submit

from .observe import ops, points, window

MODULE = "urn:kk:module:observer-otel"
AGENT = "urn:kk:agent:observer-otel"
SCOPE = "urn:kk:scope:default"
CONFIG = Path(__file__).resolve().parents[1] / "metrics.yaml"
GRACE = 1.0          # seconds after a window ends before it is recorded, for exports in flight


def decode(content_type: str, data: bytes) -> dict:
    if content_type.startswith("application/json"):
        return json.loads(data)
    if content_type.startswith("application/x-protobuf"):
        from google.protobuf.json_format import MessageToDict
        from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
        req = ExportMetricsServiceRequest()
        req.ParseFromString(data)
        return MessageToDict(req)          # the OTLP JSON shape: camelCase, 64-bit integers as strings
    raise ValueError(f"unsupported content type {content_type!r}")


class Buffer:
    def __init__(self):
        self.lock = threading.Lock()
        self.points: list[dict] = []
        self.recorded_until = 0.0

    def add(self, pts: list[dict]) -> None:
        with self.lock:
            self.points += [p for p in pts if p["t"] >= self.recorded_until]

    def take(self, end: float) -> list[dict]:
        with self.lock:
            taken = [p for p in self.points if p["t"] < end]
            self.points = [p for p in self.points if p["t"] >= end]
            self.recorded_until = max(self.recorded_until, end)
        return taken


def handler(buffer: Buffer):
    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path.rstrip("/") != "/v1/metrics":
                self.send_error(404)
                return
            try:
                body = decode(self.headers.get("Content-Type", ""), self.rfile.read(int(self.headers.get("Content-Length", 0))))
                buffer.add(points(body))
            except Exception as e:           # a malformed request is the sender's problem: 400, keep serving
                self.send_error(400, str(e)[:200])
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass
    return Receiver


def record(conn, pts: list[dict], start: float, end: float, config: dict, source: str) -> dict:
    found = ops(pts, start, end, config, source)
    if not found:
        return {"window_end": end, "observations": 0}
    cs = {"idempotency_key": f"observer-otel:{source}|{end:.0f}", "attributed_to": AGENT, "target_scope": SCOPE,
          "ops": found}
    with conn.cursor() as cur, run(cur, MODULE, {"window_end": end}) as (run_id, outputs):
        res = submit(cur, cs, run_id)
        outputs.update(observations=len(found))
    return {"window_end": end, "observations": len(found), "change_set": str(res["id"]), "status": res["status"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Record OpenTelemetry metrics as observations, once per window.")
    ap.add_argument("--port", type=int, default=int(os.environ.get("KK_OTLP_PORT", "4318")))
    a = ap.parse_args(argv)
    seconds = float(os.environ.get("KK_WINDOW_SECONDS", "60"))
    source = os.environ.get("KK_OTLP_SOURCE", f"http://{socket.gethostname()}:{a.port}/v1/metrics")
    config = yaml.safe_load(CONFIG.read_text())
    conn = connect(os.environ.get("KK_ROLE", "kkm_observer_otel"))
    buffer = Buffer()
    buffer.recorded_until = window(time.time(), seconds)[1]     # the window in progress is the first recorded
    server = ThreadingHTTPServer(("0.0.0.0", a.port), handler(buffer))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(json.dumps({"listening": a.port, "window_seconds": seconds}), flush=True)
    while True:
        end = window(time.time(), seconds)[1] + seconds
        time.sleep(max(0.0, end + GRACE - time.time()))
        try:
            print(json.dumps(record(conn, buffer.take(end), end - seconds, end, config, source)), flush=True)
        except Exception as e:               # the record is unreachable: say so; the next window tries again
            print(json.dumps({"error": str(e)[:300]}), file=sys.stderr, flush=True)


if __name__ == "__main__":
    sys.exit(main())
