import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from morphogen.telemetry import Filtering

ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = json.loads((ROOT / "examples" / "self-blueprint.json").read_text())
PG_URL = os.environ.get("MORPHOGEN_TEST_DATABASE_URL")

SPANS = InMemorySpanExporter()
_provider = TracerProvider(resource=Resource.create({"service.name": "intake",
                                                     "deployment.environment": "sandbox"}))
_provider.add_span_processor(Filtering(SimpleSpanProcessor(SPANS)))
trace.set_tracer_provider(_provider)


@pytest.fixture
def spans():
    SPANS.clear()
    return SPANS


def _pg_store():
    from morphogen.store.postgres import PostgresStore

    s = PostgresStore(PG_URL)
    with s.transaction(), s.conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS map CASCADE; DROP SCHEMA IF EXISTS api CASCADE")
    s.ensure_schema()
    return s


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.postgres)])
def store(request):
    if request.param == "memory":
        from morphogen.store import MemoryStore

        yield MemoryStore()
        return
    if not PG_URL:
        pytest.skip("MORPHOGEN_TEST_DATABASE_URL not set")
    s = _pg_store()
    yield s
    s.conn.close()


@pytest.fixture
def intent_dir(tmp_path):
    """An intent/ that is its own git repository, with the repo's policies."""
    d = tmp_path / "intent"
    shutil.copytree(ROOT / "intent" / "policies", d / "policies")
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", "add", "."], check=True)
    subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"],
                   check=True)
    return d


@pytest.fixture
def rt(store, tmp_path, intent_dir, monkeypatch):
    from morphogen import runtime
    from morphogen.store import MemoryStore

    if not isinstance(store, MemoryStore):  # readers get their own connections, as deployed
        monkeypatch.setenv("MORPHOGEN_READ_DATABASE_URL", PG_URL)

    return runtime.build(store=store, archive_dir=tmp_path / "archive", intent_dir=intent_dir)


@pytest.fixture
def client(rt):
    from fastapi.testclient import TestClient

    from morphogen.intake.app import create_app

    with TestClient(create_app(rt, sweep_interval_s=0)) as c:
        yield c


@pytest.fixture
def blueprint():
    return json.loads(json.dumps(BLUEPRINT))
