"""Metrics from providers as OpenTelemetry (OTLP/HTTP, JSON encoding). Standard library only.

  m = metrics()                       # from the environment; does nothing when no endpoint is set
  m.record("kk.feed.lag", 0.8, "s")   # one value; each export sends count, sum, min and max per name

Enabled by the standard variables: OTEL_EXPORTER_OTLP_METRICS_ENDPOINT (the full URL), or
OTEL_EXPORTER_OTLP_ENDPOINT (then <endpoint>/v1/metrics); OTEL_SERVICE_NAME names the resource
(service.name), defaulting to the provider's role; OTEL_METRIC_EXPORT_INTERVAL in milliseconds
(default 10000); OTEL_EXPORTER_OTLP_METRICS_HEADERS or OTEL_EXPORTER_OTLP_HEADERS add request headers
(`key=value,key=value`, values URL-encoded; e.g. Authorization=Bearer%20<token>). Values are sent as delta
histograms with one bucket, so any OTLP receiver (an OpenTelemetry Collector, or a distribution's
observer) can read them. Export failures are dropped: metrics
are observations about the provider, never part of the record's guarantees.
"""
from __future__ import annotations

import atexit
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from typing import Optional


class Metrics:
    def __init__(self, url: Optional[str], service: str, interval: float = 10.0, headers: Optional[dict] = None):
        self.url, self.service, self.interval = url, service, interval
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self._lock = threading.Lock()
        self._points: dict[str, list] = {}          # name -> [unit, count, sum, min, max]
        self._start = time.time_ns()
        if url:
            threading.Thread(target=self._loop, daemon=True).start()
            atexit.register(self.flush)

    def record(self, name: str, value: float, unit: str = "") -> None:
        if not self.url:
            return
        with self._lock:
            p = self._points.get(name)
            if p is None:
                self._points[name] = [unit, 1, value, value, value]
            else:
                p[1] += 1
                p[2] += value
                p[3] = min(p[3], value)
                p[4] = max(p[4], value)

    def body(self) -> Optional[dict]:
        """The OTLP request for what was recorded since the last export (and reset), or None."""
        with self._lock:
            points, self._points = self._points, {}
            start, self._start = self._start, time.time_ns()
        if not points:
            return None
        now = str(time.time_ns())
        metrics = [{"name": name, "unit": unit, "histogram": {"aggregationTemporality": 1, "dataPoints": [
            {"startTimeUnixNano": str(start), "timeUnixNano": now, "count": str(n), "sum": s,
             "min": lo, "max": hi, "bucketCounts": [str(n)], "explicitBounds": []}]}}
            for name, (unit, n, s, lo, hi) in sorted(points.items())]
        return {"resourceMetrics": [{
            "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": self.service}}]},
            "scopeMetrics": [{"scope": {"name": "kk"}, "metrics": metrics}]}]}

    def flush(self) -> None:
        body = self.body()
        if body is None or not self.url:
            return
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=self.headers, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5).close()
        except OSError:
            pass

    def _loop(self) -> None:
        while True:
            time.sleep(self.interval)
            self.flush()


_metrics: Optional[Metrics] = None


def headers(spec: str) -> dict:
    """The OpenTelemetry header list `key=value,key=value` (values URL-encoded) as a dict."""
    out = {}
    for item in filter(None, (x.strip() for x in spec.split(","))):
        key, sep, value = item.partition("=")
        if sep and key.strip():
            out[urllib.parse.unquote(key.strip())] = urllib.parse.unquote(value.strip())
    return out


def metrics(service: Optional[str] = None) -> Metrics:
    """The process's metrics, configured from the environment on first use."""
    global _metrics
    if _metrics is None:
        url = os.environ.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
        if not url and os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            url = os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"].rstrip("/") + "/v1/metrics"
        _metrics = Metrics(url, os.environ.get("OTEL_SERVICE_NAME") or service or "unknown",
                           float(os.environ.get("OTEL_METRIC_EXPORT_INTERVAL", "10000")) / 1000,
                           headers(os.environ.get("OTEL_EXPORTER_OTLP_METRICS_HEADERS")
                                   or os.environ.get("OTEL_EXPORTER_OTLP_HEADERS") or ""))
    return _metrics
