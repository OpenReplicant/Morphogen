"""Intake: CloudEvents over HTTP and OTLP/HTTP from the OTel Collector (invariant 4).

- POST /events          structured-mode CloudEvents, validated against schemas/events/
- POST /otlp/v1/traces  OTLP/HTTP (protobuf or JSON) from the Collector only

Reads for people and agents go through PostgREST or the map MCP server; the
promoter's review queue is exposed read-only here because it is governance
state, not map data.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from google.protobuf.message import DecodeError
from opentelemetry.trace import SpanKind
from starlette.concurrency import run_in_threadpool

from morphogen import queries, runtime, telemetry
from morphogen.events import INTERNAL_TYPES, make, short_type
from morphogen.ingest.traces import from_protobuf
from morphogen.intake.router import InvalidEvent
from morphogen.promoter import expire
from morphogen.watchers.drift import run_sweeps


def create_app(rt: runtime.Runtime | None = None, sweep_interval_s: float | None = None) -> FastAPI:
    state: dict = {"rt": rt}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        telemetry.setup("intake")
        if state["rt"] is None:
            state["rt"] = runtime.build()
            ensure = getattr(state["rt"].store, "ensure_schema", None)
            if ensure:
                ensure()
        stop = threading.Event()
        interval = sweep_interval_s if sweep_interval_s is not None else \
            float(os.environ.get("MORPHOGEN_SWEEP_INTERVAL_S", "60"))
        if interval > 0:
            threading.Thread(target=run_sweeps, args=(state["rt"].drift, interval, stop),
                             daemon=True).start()
        yield
        stop.set()

    app = FastAPI(title="morphogen-intake", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])

    def rt_() -> runtime.Runtime:
        return state["rt"]

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.post("/events", status_code=202)
    async def receive(request: Request) -> dict:
        body = await request.body()
        return await run_in_threadpool(_receive, rt_(), request.headers, body)

    @app.post("/otlp/v1/traces")
    async def otlp(request: Request) -> dict:
        body = await request.body()
        try:
            payload = json.loads(body or b"{}") if "json" in request.headers.get("content-type", "") \
                else from_protobuf(body)
        except (ValueError, DecodeError):
            raise HTTPException(status_code=400, detail=["unreadable OTLP payload"]) from None
        agent = request.headers.get("user-agent", "")
        sender = "collector" if "OpenTelemetry Collector" in agent else None
        await run_in_threadpool(rt_().router.submit_otlp, payload, sender)
        return {}  # ExportTraceServiceResponse

    @app.get("/review/proposals")
    def proposals(target: str | None = None, state: str | None = None) -> list[dict]:
        expire(rt_().promoter.state)
        return [p.as_dict() for p in rt_().promoter.state.list(target, state)]

    @app.post("/review/decisions", status_code=202)
    async def decide(request: Request) -> dict:
        """A person's decision. Identity comes from the gateway's forward_auth header, never the body.

        Off unless MORPHOGEN_TRUST_REMOTE_USER=1, which is safe only when the intake is reachable
        solely through Caddy with forward_auth (which overwrites Remote-User).
        """
        if os.environ.get("MORPHOGEN_TRUST_REMOTE_USER") != "1":
            detail = "review decisions need forward_auth; see MORPHOGEN_TRUST_REMOTE_USER"
            raise HTTPException(status_code=403, detail=[detail])
        user = request.headers.get("remote-user", "").strip()
        if not user:
            raise HTTPException(status_code=401, detail=["no authenticated reviewer"])
        body = await request.json()
        event = make("proposal.decided", f"person:{user}",
                     {k: body[k] for k in ("proposal_id", "decision", "reason") if k in body})
        try:
            await run_in_threadpool(rt_().submit, event)
        except InvalidEvent as e:
            raise HTTPException(status_code=400, detail=e.errors)
        return {"accepted": event["id"], "reviewer": event["source"]}

    @app.get("/review/status/{target}")
    def status(target: str) -> dict:
        t = rt_().promoter.state.get_target(target)
        return {"target": target, "autonomy": t.autonomy,
                "kill_switch": t.kill_switch or rt_().promoter.policy.killed(),
                "open_proposals": [p.id for p in rt_().promoter.state.list(target, "pending")]}

    @app.get("/metrics/map")
    def map_metrics(environment: str = "sandbox") -> dict:
        return queries.metrics(rt_().drift.store, environment)  # reader connection

    return app


def _receive(rt: runtime.Runtime, headers, body: bytes) -> dict:
    with telemetry.extracted(headers), telemetry.span("receive event", "intake", SpanKind.SERVER):
        try:
            event = json.loads(body)
        except ValueError:
            raise HTTPException(status_code=400, detail=["body is not JSON"])
        if isinstance(event, dict) and short_type(event) in INTERNAL_TYPES:
            raise HTTPException(status_code=400,
                                detail=[f"{event.get('type')} is not accepted from outside"])
        try:
            rt.submit(event)
        except InvalidEvent as e:
            raise HTTPException(status_code=400, detail=e.errors)
        return {"accepted": event["id"], "type": short_type(event)}


app = create_app()
