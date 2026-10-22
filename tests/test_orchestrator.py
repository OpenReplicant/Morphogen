"""The Compose adapter reconciles intent/environments/<env>/ and continues the promoter's trace."""

from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans

from morphogen.orchestrators.compose import ComposeAdapter, run
from tests.test_promoter import COMPOSE, decide, proposal


class Recorder:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.fail = fail

    def __call__(self, cmd: list[str]) -> tuple[int, str]:
        if cmd[0] == "git":
            return run(cmd)
        self.calls.append(cmd)
        return (1, "boom") if self.fail else (0, "")


def write(intent_dir, rel, content=COMPOSE):
    p = intent_dir / "environments" / "sandbox" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def test_up_with_every_compose_file_in_path_order(intent_dir):
    write(intent_dir, "web/compose.yml")
    write(intent_dir, "echo/compose.yml")
    write(intent_dir, "echo/notes.txt", "ignored")
    r = Recorder()
    res = ComposeAdapter(intent_dir, runner=r).reconcile()
    assert res.ok and r.calls == [[
        "docker", "compose", "-p", "morphogen-sandbox",
        "-f", str(intent_dir / "environments/sandbox/echo/compose.yml"),
        "-f", str(intent_dir / "environments/sandbox/web/compose.yml"),
        "up", "-d", "--remove-orphans"]]


def test_unchanged_folder_is_not_reapplied(intent_dir):
    write(intent_dir, "echo/compose.yml")
    r = Recorder()
    a = ComposeAdapter(intent_dir, runner=r)
    a.reconcile()
    assert a.reconcile().skipped == "unchanged" and len(r.calls) == 1
    write(intent_dir, "echo/compose.yml", COMPOSE + "    ports: ['8081:80']\n")
    assert a.reconcile().ok and len(r.calls) == 2


def test_failure_is_retried(intent_dir):
    write(intent_dir, "echo/compose.yml")
    r = Recorder(fail=True)
    a = ComposeAdapter(intent_dir, runner=r)
    assert not a.reconcile().ok
    r.fail = False
    assert a.reconcile().ok and len(r.calls) == 2


def test_empty_folder_only_pruned_when_asked(intent_dir):
    r = Recorder()
    assert ComposeAdapter(intent_dir, runner=r).reconcile().skipped == "no compose files"
    assert r.calls == []
    ComposeAdapter(intent_dir, runner=r, prune_empty=True).reconcile()
    assert r.calls == [["docker", "compose", "-p", "morphogen-sandbox", "down", "--remove-orphans"]]


def test_reconcile_continues_the_promoters_trace(client, rt, intent_dir, spans, monkeypatch):
    """Committed intent -> reconcile: promoter -> orchestrator -> docker become observed."""
    monkeypatch.setenv("MORPHOGEN_TRUST_REMOTE_USER", "1")
    p = proposal()
    client.post("/events", json=p)
    assert decide(client, p["id"]).status_code == 202
    assert "Traceparent: 00-" in run(["git", "-C", str(intent_dir), "log", "-1", "--format=%B"])[1]

    ComposeAdapter(intent_dir, runner=Recorder()).reconcile()
    client.post("/otlp/v1/traces", content=encode_spans(spans.get_finished_spans()).SerializeToString(),
                headers={"content-type": "application/x-protobuf"})
    observed = {(c.source_slot, c.target_slot) for c in rt.store.query(kind="Coupling", status="observed")}
    assert {("promoter", "orchestrator"), ("orchestrator", "docker")} <= observed
