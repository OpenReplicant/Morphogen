"""The observer slot: measurements taken outside the code under test, around each timed run.

An observer is told when a run starts (it may add environment variables for the run) and asked,
after the run, for its metrics; they become `observed.*`. The judge lets an observed metric decide a
verdict only if the target declares its data is collected outside the code under test
(`collected: outside`).

Types:

- `command` (the default when `run` is given): a command from the base commit, run in the base's
  directory after each run, that prints one JSON object of numbers. It can query anything: a
  Prometheus server, a proxy's access log, a cloud bill.
- `otel`: an OpenTelemetry (OTLP/HTTP, JSON) receiver inside the judge. Before each run the judge
  points the run's telemetry at it (for Claude Code: CLAUDE_CODE_ENABLE_TELEMETRY and the OTEL_*
  exporter variables) and tags the run with its id (OTEL_RESOURCE_ATTRIBUTES); after the run it adds
  up what arrived for that id. It keeps no traces and draws no dashboards: only each run's totals.

  observer:
    type: otel
    collected: outside            # the harness (e.g. Claude Code itself) emits, not the candidate's code
    settle_ms: 1500               # wait after the run for the last export
    metrics:
      cost_usd:      {metric: claude_code.cost.usage}                        # sum of data points
      output_tokens: {metric: claude_code.token.usage, where: {type: output}}
      tool_failures: {event: claude_code.tool_result, where: {success: "false"}, count: true}
      api_ms:        {event: claude_code.api_request, field: duration_ms}    # sum of a field

  A run that sends nothing is refused (switching telemetry off must not look free), and so is a
  negative value in a sum (counts and costs only go up).

Future types, not built: Prometheus queries, vendor APIs, traces as a source for the observed
structure.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class ObserverError(Exception):
    """The observer could not measure a run. `fault` says whose fault: the candidate's run (refuse the
    candidate) or the setup's (the judge cannot judge)."""

    def __init__(self, message: str, fault: str = "setup"):
        super().__init__(message)
        self.fault = fault


# --- OTLP/HTTP JSON


def _value(v: dict) -> Any:
    for k in ("stringValue", "boolValue", "doubleValue"):
        if k in v:
            return v[k]
    if "intValue" in v:
        return int(v["intValue"])
    return None


def _attrs(items) -> dict:
    return {a.get("key"): _value(a.get("value") or {}) for a in (items or [])}


def _num(dp: dict) -> float | None:
    if "asDouble" in dp:
        return float(dp["asDouble"])
    if "asInt" in dp:
        return float(int(dp["asInt"]))
    return None


class Receiver:
    """Collects OTLP/HTTP JSON metrics and logs, grouped by the run id attribute."""

    RUN_KEY = "morphogen.run_id"

    def __init__(self):
        self.lock = threading.Lock()
        self.points: dict[str, list[dict]] = {}
        self.events: dict[str, list[dict]] = {}
        recv = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                try:
                    data = json.loads(body or b"{}")
                except ValueError:
                    self.send_response(400)
                    self.end_headers()
                    return
                if self.path.endswith("/v1/metrics"):
                    recv._metrics(data)
                elif self.path.endswith("/v1/logs"):
                    recv._logs(data)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _metrics(self, data: dict) -> None:
        for rm in data.get("resourceMetrics") or []:
            res = _attrs((rm.get("resource") or {}).get("attributes"))
            for sm in rm.get("scopeMetrics") or []:
                for m in sm.get("metrics") or []:
                    for kind in ("sum", "gauge"):
                        if kind not in m:
                            continue
                        body = m[kind]
                        for dp in body.get("dataPoints") or []:
                            attrs = {**res, **_attrs(dp.get("attributes"))}
                            p = {"name": m.get("name"), "kind": kind, "value": _num(dp), "attrs": attrs,
                                 "temporality": body.get("aggregationTemporality"),
                                 "monotonic": body.get("isMonotonic")}
                            self._add(self.points, attrs, p)

    def _logs(self, data: dict) -> None:
        for rl in data.get("resourceLogs") or []:
            res = _attrs((rl.get("resource") or {}).get("attributes"))
            for sl in rl.get("scopeLogs") or []:
                for rec in sl.get("logRecords") or []:
                    attrs = {**res, **_attrs(rec.get("attributes"))}
                    body = _value(rec.get("body") or {})
                    name = attrs.get("event.name") or (body if isinstance(body, str) else None)
                    self._add(self.events, attrs, {"name": name, "body": body, "attrs": attrs})

    def _add(self, store: dict, attrs: dict, item: dict) -> None:
        run = attrs.get(self.RUN_KEY)
        if run is None:
            return
        with self.lock:
            store.setdefault(str(run), []).append(item)

    def take(self, run_id: str) -> tuple[list[dict], list[dict]]:
        with self.lock:
            return self.points.pop(run_id, []), self.events.pop(run_id, [])


_RECEIVER: Receiver | None = None


def receiver() -> Receiver:
    global _RECEIVER
    if _RECEIVER is None:
        _RECEIVER = Receiver()
    return _RECEIVER


def _matches(name: str | None, want: str) -> bool:
    """Event names arrive as `claude_code.api_request` or as `api_request` (the event.name attribute)."""
    if not name:
        return False
    return name == want or want.endswith("." + name) or name.endswith("." + want)


def _where(attrs: dict, where: dict) -> bool:
    return all(str(attrs.get(k)) == str(v) for k, v in (where or {}).items())


class OtelObserver:
    type = "otel"

    def __init__(self, spec: dict):
        self.spec = spec
        self.metrics = spec.get("metrics") or {}
        if not self.metrics:
            raise ObserverError("an otel observer needs metrics: what to add up from the telemetry")
        self.settle = float(spec.get("settle_ms", 1500)) / 1000

    def env(self, run_id: str) -> dict[str, str]:
        r = receiver()
        return {
            "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
            "OTEL_METRICS_EXPORTER": "otlp",
            "OTEL_LOGS_EXPORTER": "otlp",
            "OTEL_EXPORTER_OTLP_PROTOCOL": "http/json",
            "OTEL_EXPORTER_OTLP_ENDPOINT": r.endpoint,
            "OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE": "delta",
            "OTEL_METRIC_EXPORT_INTERVAL": str(int(self.spec.get("export_interval_ms", 1000))),
            "OTEL_LOGS_EXPORT_INTERVAL": str(int(self.spec.get("export_interval_ms", 1000))),
        }

    def collect(self, run_id: str) -> dict[str, float]:
        time.sleep(self.settle)
        points, events = receiver().take(run_id)
        if not points and not events:
            raise ObserverError("the run sent no telemetry (telemetry switched off, or never exported)",
                                fault="candidate")
        out = {}
        for name, m in self.metrics.items():
            if "metric" in m:
                sel = [p for p in points if p["name"] == m["metric"] and _where(p["attrs"], m.get("where"))]
                vals = [p["value"] for p in sel if p["value"] is not None]
                if any(p["kind"] == "sum" and p["value"] is not None and p["value"] < 0 for p in sel):
                    raise ObserverError(f"{m['metric']}: negative values in a sum (counts and costs only go up)",
                                        fault="candidate")
                if any(p.get("temporality") == 2 for p in sel):   # cumulative: the last point is the total
                    out[name] = max(vals) if vals else 0.0
                else:
                    out[name] = float(sum(vals))
            elif "event" in m:
                sel = [e for e in events if _matches(e["name"], m["event"]) and _where(e["attrs"], m.get("where"))]
                if m.get("count") or not m.get("field"):
                    out[name] = float(len(sel))
                else:
                    vals = [float(e["attrs"][m["field"]]) for e in sel if e["attrs"].get(m["field"]) is not None]
                    if any(v < 0 for v in vals):
                        raise ObserverError(f"{m['event']}.{m['field']}: negative values", fault="candidate")
                    out[name] = float(sum(vals))
            else:
                raise ObserverError(f"observed metric {name!r} needs metric: or event:")
        return out


OBSERVER_TYPES = ("command", "otel")
