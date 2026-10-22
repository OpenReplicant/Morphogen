"""Intake router: archive, then fan out to ingestors and subscribers.

A small in-process fan-out, not a bus (decision 0002). Every ingestor run ends
in a pipeline.completed event (decision 0006), which is archived on the
`completions` channel and delivered to completion subscribers (watchers).
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from collections.abc import Callable

from opentelemetry.trace import SpanKind

from morphogen import MAP_DATASET, telemetry
from morphogen.events import make, short_type, validate
from morphogen.ingest import Ingestor
from morphogen.ingest.traces import TraceIngestor
from morphogen.intake.archive import Archive
from morphogen.store import ChangeSet, MapStore

log = logging.getLogger(__name__)
Handler = Callable[[dict], None]


class InvalidEvent(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class Router:
    def __init__(self, store: MapStore, archive: Archive) -> None:
        self.store = store
        self.archive = archive
        self.ingestors: dict[str, list[Ingestor]] = defaultdict(list)
        self.subscribers: dict[str, list[tuple[str, Handler]]] = defaultdict(list)
        self.completion_subscribers: list[tuple[str, Handler]] = []
        self.traces = TraceIngestor()

    # -- wiring ------------------------------------------------------------

    def add_ingestor(self, ingestor: Ingestor) -> None:
        for t in ingestor.types:
            self.ingestors[t].append(ingestor)

    def subscribe(self, short: str, slot: str, handler: Handler) -> None:
        """Deliver accepted events of a type to `handler`, in a span as `slot`."""
        self.subscribers[short].append((slot, handler))

    def on_completion(self, slot: str, handler: Handler) -> None:
        self.completion_subscribers.append((slot, handler))

    # -- intake ------------------------------------------------------------

    def submit(self, event: dict, checks: Callable[[dict], list[str]] | None = None) -> str:
        """Validate, archive, ingest, notify. Raises InvalidEvent on schema errors."""
        errors = validate(event)
        if not errors and checks:
            errors = checks(event)
        if errors:
            raise InvalidEvent(errors)
        short = short_type(event)
        # The router is the intake slot, also for events published in-process.
        with telemetry.span(f"intake {short}", "intake", SpanKind.CONSUMER):
            self.archive.append("events", event)
            for ingestor in self.ingestors.get(short, []):
                self._run(ingestor.pipeline, event["id"], event.get("environment", "sandbox"),
                          lambda ing=ingestor: ing.run(event, self.store))
            for slot, handler in self.subscribers.get(short, []):
                self._deliver(slot, f"deliver {short}", handler, event)
        return event["id"]

    def submit_otlp(self, payload: dict, sender: str | None = None) -> dict:
        """Spans from the OTel Collector. Runs without tracing to avoid a feedback loop."""
        run_id = str(uuid.uuid4())
        with telemetry.suppressed():
            return self._run("traces", run_id, None,
                             lambda: self.traces.ingest(payload, run_id, self.store, sender))

    # -- internals ---------------------------------------------------------

    def _deliver(self, slot: str, name: str, handler: Handler, event: dict) -> None:
        with telemetry.span(name, slot, SpanKind.CONSUMER):
            try:
                handler(event)
            except Exception:  # a failing subscriber must not fail the intake
                log.exception("subscriber %s failed on %s", slot, event.get("id"))

    def _run(self, pipeline: str, source_id: str, environment: str | None,
             fn: Callable[[], ChangeSet]) -> dict:
        start = time.monotonic()
        status, errors, cs = "succeeded", [], ChangeSet()
        with telemetry.span(f"ingest {pipeline}", "ingestor", SpanKind.CONSUMER):
            try:
                cs = fn()
            except Exception as e:
                log.exception("pipeline %s failed", pipeline)
                status, errors = "failed", [f"{type(e).__name__}: {e}"]
            return self._complete(pipeline, source_id, environment, start, status, errors, cs)

    def _complete(self, pipeline: str, source_id: str, environment: str | None, start: float,
                  status: str, errors: list[str], cs: ChangeSet) -> dict:
        """Publish pipeline.completed from inside the ingestor's span: the ingestor is its source."""
        data = {
            "pipeline": pipeline,
            "run_id": str(uuid.uuid4()),
            "dataset": MAP_DATASET,
            "source_event_ids": [source_id],
            "status": status,
            "duration_ms": int((time.monotonic() - start) * 1000),
            "created": cs.created.as_dict(),
            "changed": cs.changed.as_dict(),
            "retired": cs.retired.as_dict(),
            "labels": sorted(cs.labels),
            **({"errors": errors} if errors else {}),
        }
        completion = make("pipeline.completed", f"ingestor:{pipeline}", data,
                          environment=environment or "sandbox", causationid=source_id)
        self.archive.append("completions", completion)
        for slot, handler in self.completion_subscribers:
            self._deliver(slot, "deliver pipeline.completed", handler, completion)
        return completion
