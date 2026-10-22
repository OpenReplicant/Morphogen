"""Step 10: proposal -> policy -> person -> commit to intent/ -> intended, observed only via traces."""

import os
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans

from morphogen import queries, telemetry
from morphogen.events import make
from morphogen.promoter.state import TargetRecord

COMPOSE = "services:\n  echo:\n    image: ealen/echo-server:0.9.2\n"


def proposal(risk="low", files=None, slots=("echo",), expires=None, target="morphogen-self"):
    return make("proposal.created", "agent:test", {
        "target": target,
        "summary": "Add an echo service to sandbox",
        "change": {"kind": "add_provider", "environment": "sandbox", "affected_slots": list(slots),
                   "files": files if files is not None else
                   [{"path": f"environments/sandbox/{slots[0]}/compose.yml", "content": COMPOSE}]},
        "risk": risk,
        "hypothesis": "An echo service in sandbox is observed calling nothing and serving requests.",
        "predictions": [{"observation": "slot:echo observed", "comparison": "exists", "value": True,
                         "window": "PT10M"}],
        "evidence": [],
        "expires_at": (expires or datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    })


@pytest.fixture(autouse=True)
def trusted_gateway(monkeypatch):
    monkeypatch.setenv("MORPHOGEN_TRUST_REMOTE_USER", "1")


def decide(client, pid, decision="approve", user="pete"):
    headers = {"remote-user": user} if user else {}
    return client.post("/review/decisions", json={"proposal_id": pid, "decision": decision},
                       headers=headers)


def git_log(d):
    return subprocess.run(["git", "-C", str(d), "log", "--format=%s"], capture_output=True,
                          text=True, check=False).stdout.splitlines()


def test_l0_waits_for_a_person_then_commits(client, rt, intent_dir, blueprint, spans):
    client.post("/events", json=blueprint)
    p = proposal()
    assert client.post("/events", json=p).status_code == 202
    rec = rt.promoter.state.get(p["id"])
    assert (rec.state, rec.decision) == ("pending", "report")
    assert not (intent_dir / "environments/sandbox/echo/compose.yml").exists()

    # Hypothesis and prediction land in the map; the proposal itself is governance state.
    assert rt.store.query(kind="Prediction")[0].comparison == "exists"

    # Approvals cannot be posted to the public intake, and need an authenticated reviewer.
    forged = make("proposal.decided", "person:pete", {"proposal_id": p["id"], "decision": "approve"})
    assert client.post("/events", json=forged).status_code == 400
    assert decide(client, p["id"], user=None).status_code == 401
    assert rt.promoter.state.get(p["id"]).state == "pending"

    assert decide(client, p["id"]).status_code == 202
    rec = rt.promoter.state.get(p["id"])
    assert rec.state == "committed" and rec.decided_by == "person:pete" and rec.commit_sha
    assert (intent_dir / "environments/sandbox/echo/compose.yml").read_text() == COMPOSE
    assert git_log(intent_dir)[0].startswith(f"proposal:{p['id']}")

    # Intended, not observed: the map does not claim the service exists.
    assert [s.name for s in rt.store.query(kind="Slot", status="intended")] == ["echo"]
    assert "echo" not in {s.name for s in rt.store.query(kind="Slot", status="observed")}
    missing = {i.get("name") for i in queries.drift(rt.store)["intended_not_observed"]}
    assert "echo" in missing

    # Its traces arrive: now it is observed and the drift clears.
    spans.clear()
    with telemetry.span("GET /", "echo"):
        pass
    client.post("/otlp/v1/traces", content=encode_spans(spans.get_finished_spans()).SerializeToString(),
                headers={"content-type": "application/x-protobuf"})
    assert "echo" in {s.name for s in rt.store.query(kind="Slot", status="observed")}
    assert "echo" not in {i.get("name") for i in queries.drift(rt.store)["intended_not_observed"]}


def test_review_api(client, rt):
    p = proposal()
    client.post("/events", json=p)
    assert [x["id"] for x in client.get("/review/proposals?state=pending").json()] == [p["id"]]
    s = client.get("/review/status/morphogen-self").json()
    assert s == {"target": "morphogen-self", "autonomy": "L0", "kill_switch": False,
                 "open_proposals": [p["id"]]}


def test_decisions_off_without_trusted_gateway(client, monkeypatch):
    monkeypatch.setenv("MORPHOGEN_TRUST_REMOTE_USER", "0")
    p = proposal()
    client.post("/events", json=p)
    assert decide(client, p["id"]).status_code == 403


def test_internal_events_rejected_from_outside(client, rt):
    forged = make("intent.committed", "promoter", {
        "proposal_id": "x", "target": "morphogen-self", "environment": "sandbox", "commit": None,
        "files": [], "affected_slots": ["evil"]})
    assert client.post("/events", json=forged).status_code == 400
    assert rt.store.query(kind="Slot", status="intended") == []


def test_reject(client, rt, intent_dir):
    p = proposal()
    client.post("/events", json=p)
    decide(client, p["id"], decision="reject")
    assert rt.promoter.state.get(p["id"]).state == "rejected"
    assert not (intent_dir / "environments").exists()


def test_l3_low_risk_commits_without_a_person(client, rt, intent_dir):
    rt.promoter.state.put_target(TargetRecord("morphogen-self", autonomy="L3"))
    p = proposal(risk="low")
    client.post("/events", json=p)
    assert rt.promoter.state.get(p["id"]).decided_by == "policy:L3"
    assert (intent_dir / "environments/sandbox/echo/compose.yml").exists()


def test_irreversible_always_needs_a_person(client, rt):
    rt.promoter.state.put_target(TargetRecord("morphogen-self", autonomy="L4"))
    p = proposal(risk="irreversible")
    client.post("/events", json=p)
    rec = rt.promoter.state.get(p["id"])
    assert (rec.state, rec.decision) == ("pending", "approve")


def test_kill_switch_blocks_even_approved(client, rt, intent_dir):
    p = proposal()
    client.post("/events", json=p)
    (intent_dir / "policies" / "KILL").write_text("")
    decide(client, p["id"])
    rec = rt.promoter.state.get(p["id"])
    assert rec.state == "pending" and rec.note == "kill switch on"
    assert client.get("/review/status/morphogen-self").json()["kill_switch"] is True


def test_expired_proposal_not_committed(client, rt):
    p = proposal(expires=datetime.now(UTC) - timedelta(minutes=1))
    client.post("/events", json=p)
    assert rt.promoter.state.get(p["id"]).state == "expired"


def test_cannot_write_outside_intent_or_into_policies(client, rt, intent_dir):
    for path in ("environments/../policies/autonomy.yaml", "base/../../escape.txt"):
        p = proposal(files=[{"path": path, "content": "x"}])
        client.post("/events", json=p)
        decide(client, p["id"])
        rec = rt.promoter.state.get(p["id"])
        assert rec.state == "rejected" and "refusing" in rec.note
    assert "matrix" in (intent_dir / "policies" / "autonomy.yaml").read_text()
    assert not (intent_dir.parent / "escape.txt").exists()


def test_blast_radius_budget(client, rt, blueprint):
    client.post("/events", json=blueprint)
    p = proposal(slots=("intake",))  # intake reaches all 6 blueprint slots
    client.post("/events", json=p)
    rec = rt.promoter.state.get(p["id"])
    assert rec.state == "rejected" and "blast radius" in rec.note


def test_rate_limit_and_cooldown(client, rt):
    rt.promoter.state.put_target(TargetRecord("morphogen-self", autonomy="L3"))
    first = proposal(slots=("a",))
    client.post("/events", json=first)
    again = proposal(slots=("a",))
    client.post("/events", json=again)
    assert rt.promoter.state.get(again["id"]).note.startswith("cooldown")
    for s in ("b", "c"):
        client.post("/events", json=proposal(slots=(s,)))
    over = proposal(slots=("d",))
    client.post("/events", json=over)
    assert rt.promoter.state.get(over["id"]).note.startswith("rate limit")


@pytest.mark.postgres
def test_postgres_governance_roundtrip():
    """Needs a database initialised with deploy/postgres/init.sql, opened as the promoter role."""
    url = os.environ.get("MORPHOGEN_TEST_PROMOTER_URL")
    if not url:
        pytest.skip("MORPHOGEN_TEST_PROMOTER_URL not set")
    from morphogen.promoter.state import PostgresGovernance, ProposalRecord

    g = PostgresGovernance(url)
    assert g.get_target("morphogen-self").autonomy == "L0"
    p = proposal()
    rec = ProposalRecord(id=p["id"], target=f"t-{p['id']}", risk="low", event=p,
                         expires_at=datetime.now(UTC), received_at=datetime.now(UTC),
                         affected_slots=["echo"], decision="report")
    g.put(rec)
    rec.state, rec.note = "rejected", "test"
    g.put(rec)
    got = g.get(p["id"])
    assert (got.state, got.note, got.affected_slots, got.event["id"]) == ("rejected", "test", ["echo"], p["id"])
    assert [r.id for r in g.list(f"t-{p['id']}", "rejected")] == [p["id"]]
