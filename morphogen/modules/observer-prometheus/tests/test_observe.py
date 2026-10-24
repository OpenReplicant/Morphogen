"""observer-prometheus: window means from two scrapes (pure), then the service scraping a stand-in target
into the record.

  PGHOST=... PGUSER=<superuser> python3 tests/test_observe.py
"""
import os
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "modules"),
                 str(ROOT / "kernel" / "providers" / "validator-shacl")]
import importlib  # noqa: E402
import install  # noqa: E402  (morphogen/modules/install.py)
from kk.lib import connect  # noqa: E402
from observer_prometheus.__main__ import targets  # noqa: E402
from observer_prometheus.observe import SOSA, ops, parse, totals  # noqa: E402

validator = importlib.import_module("validator.__main__")

DB = "kk_observer_prometheus_test"
CONFIG = yaml.safe_load((HERE / "metrics.yaml").read_text())
PROP = "urn:kk:property:latency-seconds-mean"
NODE = "urn:kk:node:demo:web"


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg)


def exposition(echo_sum, echo_n, metrics_sum=0.0, metrics_n=0):
    return f"""# HELP http_request_duration_seconds Seconds spent serving HTTP requests.
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds_bucket{{method="POST",path="api_echo",status="200",le="0.5"}} {echo_n}
http_request_duration_seconds_sum{{method="POST",path="api_echo",status="200"}} {echo_sum}
http_request_duration_seconds_count{{method="POST",path="api_echo",status="200"}} {echo_n}
http_request_duration_seconds_sum{{method="GET",path="metrics",status="200"}} {metrics_sum}
http_request_duration_seconds_count{{method="GET",path="metrics",status="200"}} {metrics_n}
go_goroutines 12
"""


check(parse('a_total{x="1",y="q\\"t"} 3.5 1700000000\n# c\nbad line\n') == [("a_total", {"x": "1", "y": 'q"t'}, 3.5)],
      "the text format: labels (escaped quotes too) and a timestamp; comments and malformed lines skipped")
t0, t1 = totals(exposition(1.0, 4, 9.0, 3), CONFIG), totals(exposition(2.5, 7, 20.0, 5), CONFIG)
check(t0 == {"http_request_duration_seconds": (1.0, 4)}, "totals leave out the excluded path (the scrape counting itself)")
got = ops(NODE, "http://h/metrics", t0, t1, 100.0, 104.0, CONFIG)
check(len(got) == 1 and got[0]["object"]["value"]["@value"] == 0.5 and got[0]["qualifiers"] == {SOSA + "observedProperty": PROP}
      and got[0]["evidence_type"] == "observed" and got[0]["subject"] == NODE
      and got[0]["references"][0]["source_uri"] == "http://h/metrics?metric=http_request_duration_seconds&from=100&to=104",
      "a window's mean is the requests finished in it: (2.5 - 1.0) / (7 - 4) = 0.5, cited by the scraped URL and window")
check(ops(NODE, "u", t1, t1, 0, 1, CONFIG) == [] and ops(NODE, "u", t1, t0, 0, 1, CONFIG) == [],
      "no requests in the window, or counters that went down (a restart): no observation")
for bad in ("web=http://h", "urn:x=ftp://h"):
    try:
        targets(bad)
        check(False, "a malformed target is refused")
    except ValueError:
        pass
check(targets(f"{NODE}=http://h:1/metrics") == {NODE: "http://h:1/metrics"}, "targets are <subject>=<url>")

# The service against a stand-in target whose requests take 0.25 s each.
state = {"sum": 0.0, "n": 0}


class Target(BaseHTTPRequestHandler):
    def do_GET(self):
        body = exposition(state["sum"], state["n"]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Target)
threading.Thread(target=server.serve_forever, daemon=True).start()
stop = threading.Event()


def traffic():
    while not stop.wait(0.1):
        state["sum"] += 0.25
        state["n"] += 1


threading.Thread(target=traffic, daemon=True).start()
subprocess.run(["dropdb", "--if-exists", DB], check=True)
os.environ.setdefault("KK_LOGIN_PASSWORD", secrets.token_hex(16))
install.install(DB, ["observer-prometheus"])
url = f"http://127.0.0.1:{server.server_address[1]}/metrics"
env = {**os.environ, "DATABASE_URL": f"dbname={DB}", "KK_WINDOW_SECONDS": "2", "KK_PROM_TARGETS": f"{NODE}={url}",
       "PYTHONPATH": os.pathsep.join([str(HERE), str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "src")])}
p = subprocess.Popen([sys.executable, "-m", "observer_prometheus"], cwd=HERE, env=env, stdout=subprocess.PIPE,
                     stderr=subprocess.STDOUT, text=True)
try:
    rows = []
    with connect(url=f"dbname={DB}") as su, connect("kkm_validator", f"dbname={DB}") as val:
        end = time.monotonic() + 30
        while time.monotonic() < end and not rows:
            time.sleep(0.5)
            validator.drain(val)
            rows = su.execute("""select (object_value->>'@value')::float, attributed_to, valid_to - valid_from
                                 from kernel.claim where subject = %s and predicate = %s and qualifiers->>%s = %s""",
                              (NODE, SOSA + "hasSimpleResult", SOSA + "observedProperty", PROP)).fetchall()
    check(rows and abs(rows[0][0] - 0.25) < 1e-6 and rows[0][1] == "urn:kk:agent:observer-prometheus"
          and rows[0][2].total_seconds() == 2,
          f"the service records the target's mean request time per 2 s window ({rows[0][0] if rows else None} s)")
finally:
    stop.set()
    p.terminate()
    out = p.communicate(timeout=10)[0]
    server.shutdown()
    subprocess.run(["dropdb", "--force", DB], check=True)
    if not rows:
        print(out[-2000:])
print("observer-prometheus tests passed")
