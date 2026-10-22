"""Steps 7 and 8: traces -> observed slots and couplings; drift lists and clears.

The spans come from Morphogen's own code paths (intake, ingestor, promoter,
map MCP client), captured in memory and re-encoded as the OTLP the Collector
would send.
"""

from google.protobuf.json_format import MessageToDict
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.trace import SpanKind

from morphogen import queries, telemetry
from tests.test_blueprint import EXPECTED_COUPLINGS

COLLECTOR_UA = {"user-agent": "OpenTelemetry Collector Contrib/0.110.0"}


def otlp(spans) -> bytes:
    return encode_spans(spans.get_finished_spans()).SerializeToString()


def send(client, body: bytes) -> None:
    r = client.post("/otlp/v1/traces", content=body,
                    headers={"content-type": "application/x-protobuf", **COLLECTOR_UA})
    assert r.status_code == 200, r.text


def pairs(rt, status="observed"):
    return {(c.source_slot, c.target_slot) for c in rt.store.query(kind="Coupling", status=status)}


def test_own_spans_become_observed_couplings(client, rt, blueprint, spans):
    client.post("/events", json=blueprint)
    send(client, otlp(spans))
    observed = pairs(rt)
    assert ("collector", "intake") in observed  # the OTLP batch itself
    assert ("intake", "ingestor") in observed  # router dispatch
    assert ("ingestor", "drift-watcher") in observed  # completion delivery
    if rt.store.__class__.__name__ == "PostgresStore":
        assert ("ingestor", "postgres") in observed
    c = next(c for c in rt.store.query(kind="Coupling", status="observed")
             if (c.source_slot, c.target_slot) == ("intake", "ingestor"))
    assert c.coupling_type == "event" and c.provenance == "discovered"
    assert rt.store.last_seen([c.key])


def test_ingesting_traces_emits_no_new_spans(client, rt, spans):
    with telemetry.span("x", "map_mcp"):
        pass
    body = otlp(spans)
    spans.clear()
    send(client, body)
    assert spans.get_finished_spans() == ()


def test_json_encoding_accepted(client, rt, spans):
    with telemetry.span("parent", "intake"):
        with telemetry.span("child", "promoter", SpanKind.CONSUMER):
            pass
    payload = MessageToDict(encode_spans(spans.get_finished_spans()))
    r = client.post("/otlp/v1/traces", json=payload)
    assert r.status_code == 200
    assert ("intake", "promoter") in pairs(rt)


def test_parent_in_earlier_batch(client, rt, spans):
    with telemetry.span("parent", "intake"):
        with telemetry.client_span("db", "intake", "postgres"):
            pass
        first = otlp(spans)  # only the client span has finished
        spans.clear()
    send(client, first)
    send(client, otlp(spans))
    assert ("intake", "postgres") in pairs(rt)


def test_drift_lists_unobserved_blueprint_couplings_and_clears(client, rt, blueprint, spans):
    client.post("/events", json=blueprint)
    d = queries.drift(rt.store)
    assert {(i["source_slot"], i["target_slot"]) for i in d["intended_not_observed"]
            if i["what"] == "coupling"} == EXPECTED_COUPLINGS

    # Simulate the rest of the running stack: MCP reads and proposes, promoter receives.
    with telemetry.span("tool slots", "map_mcp"):
        with telemetry.client_span("select", "map_mcp", "postgres"):
            pass
    with telemetry.client_span("propose", "map_mcp", "intake", **{"messaging.system": "cloudevents"}):
        with telemetry.span("receive event", "intake", SpanKind.SERVER):
            with telemetry.span("ingest", "ingestor", SpanKind.CONSUMER):
                with telemetry.client_span("insert", "ingestor", "postgres"):
                    pass
                with telemetry.span("deliver", "drift-watcher", SpanKind.CONSUMER):
                    with telemetry.client_span("select", "drift-watcher", "postgres"):
                        pass
                    with telemetry.span("intake", "intake", SpanKind.CONSUMER):
                        pass
            with telemetry.span("deliver", "promoter", SpanKind.CONSUMER):
                with telemetry.client_span("select", "promoter", "postgres"):
                    pass
                with telemetry.span("intake", "intake", SpanKind.CONSUMER):
                    pass
    send(client, otlp(spans))

    d = queries.drift(rt.store)
    assert [i for i in d["intended_not_observed"] if i["what"] == "coupling"] == []
    unexpected = {(i["source_slot"], i["target_slot"]) for i in d["observed_not_intended"]
                  if i["what"] == "coupling"}
    assert ("collector", "intake") not in unexpected
    m = queries.metrics(rt.store)
    assert m["coverage"] == 1.0 and m["expected_couplings"] == 11


def test_drift_watcher_emits_findings_on_change(client, rt, blueprint, spans):
    client.post("/events", json=blueprint)
    findings = [e for e in rt.router.archive.read("events") if e["type"].endswith("finding.created")]
    assert len(findings) == 1
    f = findings[0]["data"]
    assert f["kind"] == "drift" and f["severity"] == "warning"
    assert "morphogen-self/c3" in f["evidence"]
    assert findings[0]["causationid"]  # the completion event that triggered the check
    assert rt.drift.sweep() == []  # unchanged drift: no duplicate finding
