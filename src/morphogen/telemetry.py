"""OpenTelemetry for Morphogen's own components, so the system observes itself.

Spans carry `morphogen.slot` (the slot the code acts as) and client spans carry
`morphogen.peer.slot`; the trace ingestor turns them into observed couplings.
Exporting is on only when OTEL_EXPORTER_OTLP_ENDPOINT is set.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from opentelemetry import context, propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.trace import SpanKind

SLOT_ATTR = "morphogen.slot"
PEER_ATTR = "morphogen.peer.slot"

_configured = False


def setup(service_name: str) -> None:
    global _configured
    if _configured or not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({
        "service.name": os.environ.get("OTEL_SERVICE_NAME", service_name),
        "deployment.environment": os.environ.get("MORPHOGEN_ENVIRONMENT", "sandbox"),
    })
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(Filtering(BatchSpanProcessor(OTLPSpanExporter())))
    trace.set_tracer_provider(provider)
    _configured = True


def _otlp_route(s) -> bool:
    a = s.attributes or {}
    return str(a.get("http.route") or a.get("url.path") or "").startswith("/otlp")


class Filtering(SpanProcessor):
    """Drops every span of a trace rooted in an OTLP request.

    Exporting spans about receiving OTLP would feed back into the intake forever.
    """

    def __init__(self, inner: SpanProcessor) -> None:
        self.inner = inner
        self._dropped: set[int] = set()

    def on_start(self, span, parent_context=None) -> None:
        if _otlp_route(span):
            self._dropped.add(span.context.trace_id)
        self.inner.on_start(span, parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        tid = span.context.trace_id
        if tid in self._dropped:
            if span.parent is None:
                self._dropped.discard(tid)
            return
        self.inner.on_end(span)

    def shutdown(self) -> None:
        self.inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.inner.force_flush(timeout_millis)


def tracer():
    return trace.get_tracer("morphogen")


_suppressed: ContextVar[bool] = ContextVar("morphogen_suppress_spans", default=False)


@contextmanager
def suppressed() -> Iterator:
    """No spans inside: ingesting our own traces must not emit more traces about it."""
    token = _suppressed.set(True)
    try:
        yield
    finally:
        _suppressed.reset(token)


@contextmanager
def span(name: str, slot: str, kind: SpanKind = SpanKind.INTERNAL, **attrs) -> Iterator:
    if _suppressed.get():
        yield None
        return
    with tracer().start_as_current_span(name, kind=kind, attributes={SLOT_ATTR: slot, **attrs}) as s:
        yield s


@contextmanager
def client_span(name: str, slot: str, peer: str, **attrs) -> Iterator:
    with span(name, slot, SpanKind.CLIENT, **{PEER_ATTR: peer, **attrs}) as s:
        yield s


def inject(headers: dict) -> dict:
    propagate.inject(headers)
    return headers


@contextmanager
def extracted(headers) -> Iterator:
    token = context.attach(propagate.extract(headers))
    try:
        yield
    finally:
        context.detach(token)
