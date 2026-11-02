"""OpenTelemetry spans for Morphogen's own work (judge and measure runs).

Off unless OTEL_EXPORTER_OTLP_ENDPOINT is set; then spans go to that OTLP/HTTP
endpoint (a collector, Jaeger, Grafana, Phoenix), named by OTEL_SERVICE_NAME
(default "morphogen"). Telemetry never affects a verdict.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

_tracer = None
_tried = False


def _get():
    global _tracer, _tried
    if _tried:
        return _tracer
    _tried = True
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return None
    provider = TracerProvider(resource=Resource.create(
        {"service.name": os.environ.get("OTEL_SERVICE_NAME", "morphogen")}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("morphogen")
    return _tracer


def enabled() -> bool:
    return _get() is not None


@contextmanager
def span(name: str, **attrs):
    """A span with morphogen.* attributes, or nothing when telemetry is off."""
    tracer = _get()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(name) as s:
        for k, v in attrs.items():
            if v is not None:
                s.set_attribute(f"morphogen.{k}", v if isinstance(v, (str, int, float, bool)) else str(v))
        yield s
