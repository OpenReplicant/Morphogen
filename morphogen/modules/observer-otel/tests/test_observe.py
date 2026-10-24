"""observer-otel unit checks: OTLP requests (JSON and protobuf) become one observation per resource,
property and window, the mean over the window. No database.

  python3 tests/test_observe.py   (run in the module's directory; protobuf needs requirements.txt)
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE), str(HERE.parents[2] / "kernel" / "src")]
import yaml  # noqa: E402

from observer_otel.__main__ import Buffer, decode, handler  # noqa: E402
from observer_otel.observe import SOSA, ops, points, subject, window  # noqa: E402

CONFIG = yaml.safe_load((HERE / "metrics.yaml").read_text())
LAG = "urn:kk:property:feed-lag-seconds-mean"


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg)


def request(service, metric, t, count, total):
    return {"resourceMetrics": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]},
        "scopeMetrics": [{"scope": {"name": "kk"}, "metrics": [{"name": metric, "unit": "s", "histogram": {
            "aggregationTemporality": 1, "dataPoints": [{"startTimeUnixNano": "0", "timeUnixNano": str(int(t * 1e9)),
                                                         "count": str(count), "sum": total}]}}]}]}]}


check(window(1000.5, 60) == (900, 960), "the last complete window, aligned to the clock")
check(subject(CONFIG["subject"], {"service.name": "belief-corroboration"}) == "urn:kk:provider:belief-corroboration"
      and subject(CONFIG["subject"], {}) is None, "the subject comes from service.name; none without it")
pts = (points(request("belief-corroboration", "kk.feed.lag", 905, 2, 3.0))
       + points(request("belief-corroboration", "kk.feed.lag", 930, 2, 1.0))
       + points(request("belief-corroboration", "kk.feed.lag", 961, 5, 100.0))      # the next window
       + points(request("belief-corroboration", "kk.unmapped", 910, 1, 1.0))
       + points({"resourceMetrics": [{"resource": {}, "scopeMetrics": [{"metrics": [{"name": "kk.feed.lag",
                "histogram": {"dataPoints": [{"timeUnixNano": "910000000000", "count": "1", "sum": 9}]}}]}]}]}))
out = ops(pts, 900, 960, CONFIG, "http://observer:4318/v1/metrics")
check(len(out) == 1, "one observation: other windows, unmapped metrics and unnamed resources are left out")
o = out[0]
check(o["subject"] == "urn:kk:provider:belief-corroboration" and o["predicate"] == SOSA + "hasSimpleResult"
      and o["object"]["value"]["@value"] == 1.0 and o["qualifiers"] == {SOSA + "observedProperty": LAG},
      "the mean over the window (4 values summing to 4.0)")
check(o["valid_from"].startswith("1970-01-01T00:15:00") and o["valid_to"].startswith("1970-01-01T00:16:00")
      and o["evidence_type"] == "observed" and o["references"][0]["source_uri"].startswith("http://observer:4318/v1/metrics?"),
      "valid for the window, observed, referenced by the receiver")
gauge = {"resourceMetrics": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "x"}}]},
         "scopeMetrics": [{"metrics": [{"name": "kk.step.duration", "gauge": {"dataPoints": [
             {"timeUnixNano": "910000000000", "asDouble": 0.5}, {"timeUnixNano": "911000000000", "asInt": "1"}]}}]}]}]}
g = ops(points(gauge), 900, 960, CONFIG, "s")
check(len(g) == 1 and g[0]["object"]["value"]["@value"] == 0.75, "gauges: the mean of their values")
b = Buffer()
b.add(pts)
taken = b.take(960)
b.add(points(request("belief-corroboration", "kk.feed.lag", 950, 1, 1.0)))
check(len(taken) == 4 and all(p["t"] >= 960 for p in b.points), "a recorded window takes its points; late ones are dropped")

import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

from morphogen.logins import telemetry_token  # noqa: E402
TOKEN = telemetry_token("s3cret", "belief-corroboration")
buf = Buffer()
srv = ThreadingHTTPServer(("127.0.0.1", 0), handler(buf, "s3cret", {"belief-corroboration", "validator-shacl"}, max_bytes=10_000))
threading.Thread(target=srv.serve_forever, daemon=True).start()


def post(body, auth=f"Bearer {TOKEN}"):
    req = urllib.request.Request(f"http://127.0.0.1:{srv.server_port}/v1/metrics", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **({"Authorization": auth} if auth else {})})
    try:
        return urllib.request.urlopen(req, timeout=5).status
    except urllib.error.HTTPError as e:
        return e.code


now = time.time()
check(post(request("belief-corroboration", "kk.feed.lag", now, 1, 1.0), auth=None) == 401
      and post(request("belief-corroboration", "kk.feed.lag", now, 1, 1.0), auth="Bearer wrong") == 401 and not buf.points,
      "no token, or the wrong one: refused, nothing kept")
check(post(request("belief-corroboration", "kk.feed.lag", now, 1, 1.0), auth="Bearer s3cret") == 401 and not buf.points,
      "the secret itself is not a token")
check(post(request("belief-corroboration", "kk.feed.lag", now, 1, 1.0)) == 200 and len(buf.points) == 1, "the service's own token: accepted")
check(post(request("validator-shacl", "kk.feed.lag", now, 1, 1.0)) == 401 and len(buf.points) == 1,
      "one service's token does not report as another (even one on the list): refused, nothing kept")
post(request("someone-else", "kk.feed.lag", now, 1, 1.0), auth=f"Bearer {telemetry_token('s3cret', 'someone-else')}")
post(request("belief-corroboration", "kk.feed.lag", now + 3600, 1, 1.0))
check(len(buf.points) == 1, "resources not on the list, and points stamped far ahead, are dropped")
check(post({"resourceMetrics": [], "pad": "x" * 20_000}) == 413, "a request over the size limit is refused")
srv.shutdown()
from observer_otel.__main__ import allowed  # noqa: E402
check(allowed("anomaly-fast", {"anomaly*"}) and allowed("anomaly", {"anomaly*"}) and not allowed("validator", {"anomaly*"})
      and not allowed(None, {"*"}), "a list entry ending in * allows a prefix")

try:
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    from google.protobuf.json_format import ParseDict
except ImportError:
    sys.exit("FAIL: opentelemetry-proto is not installed (pip install -r requirements.txt)")
body = request("belief-corroboration", "kk.feed.lag", 905, 2, 3.0)
wire = ParseDict(body, ExportMetricsServiceRequest()).SerializeToString()
check(points(decode("application/x-protobuf", wire)) == points(body), "protobuf requests read the same as JSON")
