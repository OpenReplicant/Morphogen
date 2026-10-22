"""Trace ingestor: OTLP spans -> observed slots and couplings.

A span's slot is its `morphogen.slot` attribute, else its resource's
`service.name`. Couplings come from two signals:

- a span whose parent belongs to a different slot (parent slot -> child slot);
- a client or producer span naming its peer (`morphogen.peer.slot`,
  `peer.service`, or `db.system`).

The sender of the OTLP request is itself observed: the collector -> intake
stream coupling exists because the batch arrived.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from datetime import UTC, datetime

from morphogen.domain.ontology import Claim, Coupling, CouplingType, Provenance, Slot, Status, now
from morphogen.store import ChangeSet, MapStore
from morphogen.telemetry import PEER_ATTR, SLOT_ATTR

SPAN_KIND = {1: "internal", 2: "server", 3: "client", 4: "producer", 5: "consumer"}
_KIND_NAMES = {f"SPAN_KIND_{v.upper()}": v for v in SPAN_KIND.values()}


def slot_key(name: str) -> str:
    return f"slot/{name}"


def coupling_key(src: str, dst: str) -> str:
    return f"coupling/{src}->{dst}"


def _attrs(items: Iterable[dict] | None) -> dict:
    out = {}
    for a in items or []:
        v = a.get("value", {})
        out[a["key"]] = next(iter(v.values()), None) if v else None
    return out


def _kind(span: dict) -> str:
    k = span.get("kind", 1)
    return SPAN_KIND.get(k, "internal") if isinstance(k, int) else _KIND_NAMES.get(k, "internal")


def _time(nanos) -> datetime:
    return datetime.fromtimestamp(int(nanos or 0) / 1e9, tz=UTC)


def flatten(payload: dict) -> list[dict]:
    """OTLP/JSON ExportTraceServiceRequest -> spans with resolved slot, env and times."""
    spans = []
    for rs in payload.get("resourceSpans", []):
        res = _attrs(rs.get("resource", {}).get("attributes"))
        env = res.get("morphogen.environment") or res.get("deployment.environment") or "sandbox"
        for ss in rs.get("scopeSpans", []):
            for s in ss.get("spans", []):
                attrs = _attrs(s.get("attributes"))
                spans.append({
                    "span_id": s.get("spanId"),
                    "parent_id": s.get("parentSpanId") or None,
                    "kind": _kind(s),
                    "slot": attrs.get(SLOT_ATTR) or res.get("service.name") or "unknown",
                    "peer": attrs.get(PEER_ATTR) or attrs.get("peer.service") or attrs.get("db.system"),
                    "messaging": bool(attrs.get("messaging.system")),
                    "environment": env if env in ("sandbox", "staging", "production") else "sandbox",
                    "start": _time(s.get("startTimeUnixNano")),
                    "end": _time(s.get("endTimeUnixNano")),
                })
    return spans


def from_protobuf(body: bytes) -> dict:
    from google.protobuf.json_format import MessageToDict
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    msg = ExportTraceServiceRequest()
    msg.ParseFromString(body)
    return MessageToDict(msg)


class TraceIngestor:
    pipeline = "traces"
    types = ()  # fed by the OTLP endpoint, not by CloudEvents

    def __init__(self, cache_size: int = 50_000) -> None:
        # span id -> (slot, is event-like), so a child arriving in a later batch still finds
        # its parent's slot, and both signals for one hop agree on the coupling type
        self._slots: OrderedDict[str, tuple[str, bool]] = OrderedDict()
        self._cache_size = cache_size

    def _remember(self, span_id: str, slot: str, evented: bool) -> None:
        self._slots[span_id] = (slot, evented)
        self._slots.move_to_end(span_id)
        while len(self._slots) > self._cache_size:
            self._slots.popitem(last=False)

    def claims(self, payload: dict, run_id: str, sender: str | None = None) -> tuple[list[Claim], dict]:
        spans = flatten(payload)
        for s in spans:
            s["evented"] = s["kind"] in ("producer", "consumer") or s["messaging"]
            if s["span_id"]:
                self._remember(s["span_id"], s["slot"], s["evented"])

        recorded = now()
        common = dict(status=Status.OBSERVED, provenance=Provenance.DISCOVERED, confidence=0.9,
                      source_event_id=run_id, recorded_at=recorded)
        slots: dict[tuple, Slot] = {}
        couplings: dict[tuple, Coupling] = {}
        seen: dict[str, datetime] = {}

        def add_slot(name: str, env: str, t: datetime) -> None:
            k = (name, env)
            if k not in slots or slots[k].valid_from > t:
                slots[k] = Slot(key=slot_key(name), role="observed", name=name, environment=env,
                                valid_from=t, **common)
            seen[slot_key(name)] = max(seen.get(slot_key(name), t), t)

        def add_coupling(src: str, dst: str, ctype: CouplingType, env: str, start: datetime,
                         end: datetime) -> None:
            if src == dst:
                return
            add_slot(src, env, start)
            add_slot(dst, env, start)
            k = (src, dst, env)
            if k not in couplings or couplings[k].valid_from > start:
                couplings[k] = Coupling(key=coupling_key(src, dst), coupling_type=ctype,
                                        source_slot=src, target_slot=dst, environment=env,
                                        valid_from=start, **common)
            seen[coupling_key(src, dst)] = max(seen.get(coupling_key(src, dst), end), end)

        for s in spans:
            add_slot(s["slot"], s["environment"], s["start"])
            parent = self._slots.get(s["parent_id"]) if s["parent_id"] else None
            if parent:
                ctype = CouplingType.EVENT if s["evented"] or parent[1] else CouplingType.CALL
                add_coupling(parent[0], s["slot"], ctype, s["environment"], s["start"], s["end"])
            if s["peer"] and s["kind"] in ("client", "producer"):
                ctype = CouplingType.EVENT if s["evented"] else CouplingType.CALL
                add_coupling(s["slot"], s["peer"], ctype, s["environment"], s["start"], s["end"])

        if sender and spans:
            first = min(s["start"] for s in spans)
            env = spans[0]["environment"]
            add_coupling(sender, "intake", CouplingType.STREAM, env, first, recorded)

        return [*slots.values(), *couplings.values()], seen

    def ingest(self, payload: dict, run_id: str, store: MapStore, sender: str | None = None) -> ChangeSet:
        claims, seen = self.claims(payload, run_id, sender)
        with store.transaction():
            cs = store.upsert(claims)
            for key, t in seen.items():
                store.touch([key], t)
        return cs
