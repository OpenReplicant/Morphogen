"""Wires the intake's slots together: store, archive, router, ingestors, promoter, watchers.

Each part is a default provider behind its own interface (invariant 6); tests
build a Runtime with in-memory providers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from morphogen.ingest.blueprint import BlueprintIngestor
from morphogen.ingest.blueprint import check as check_blueprint
from morphogen.ingest.intent import IntentIngestor
from morphogen.ingest.proposals import ProposalIngestor
from morphogen.intake.archive import Archive
from morphogen.intake.router import Router
from morphogen.promoter import SLOT as PROMOTER
from morphogen.promoter import Promoter
from morphogen.promoter.state import GovernanceState, PostgresGovernance
from morphogen.store import MapStore, MemoryStore, open_store
from morphogen.watchers.drift import SLOT as DRIFT
from morphogen.watchers.drift import DriftWatcher

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Runtime:
    store: MapStore
    router: Router
    promoter: Promoter
    drift: DriftWatcher

    def submit(self, event: dict) -> str:
        return self.router.submit(event, checks=_checks)


def _checks(event: dict) -> list[str]:
    if event["type"].endswith("blueprint.submitted"):
        return check_blueprint(event)
    return []


def _reader(slot: str, fallback: MapStore) -> MapStore:
    """Watchers and the promoter read the map with the read-only role when one is configured."""
    dsn = os.environ.get("MORPHOGEN_READ_DATABASE_URL")
    if not dsn:
        if not isinstance(fallback, MemoryStore):
            raise RuntimeError("MORPHOGEN_READ_DATABASE_URL is required with a database map store: "
                               f"{slot} must not read through the ingestor's connection")
        return fallback
    from morphogen.store.postgres import PostgresStore

    return PostgresStore(dsn, slot=slot)


def build(store: MapStore | None = None, archive_dir: str | Path | None = None,
          intent_dir: str | Path | None = None, governance: GovernanceState | None = None,
          target: str | None = None) -> Runtime:
    store = store or open_store()
    archive = Archive(archive_dir or os.environ.get("MORPHOGEN_ARCHIVE_DIR", ROOT / ".data" / "archive"))
    router = Router(store, archive)
    for ingestor in (BlueprintIngestor(), ProposalIngestor(), IntentIngestor()):
        router.add_ingestor(ingestor)

    rt: Runtime  # publish callbacks re-enter through validation
    publish = lambda e: rt.submit(e)

    if governance is None and os.environ.get("MORPHOGEN_PROMOTER_DATABASE_URL"):
        governance = PostgresGovernance(os.environ["MORPHOGEN_PROMOTER_DATABASE_URL"])
    promoter = Promoter(intent_dir or os.environ.get("MORPHOGEN_INTENT_DIR", ROOT / "intent"),
                        _reader(PROMOTER, store), publish, state=governance)
    router.subscribe("proposal.created", PROMOTER, promoter.on_proposal)
    router.subscribe("proposal.decided", PROMOTER, promoter.on_decision)

    drift = DriftWatcher(_reader(DRIFT, store), publish, target or os.environ.get("MORPHOGEN_TARGET", "morphogen-self"))
    router.on_completion(DRIFT, drift.on_completion)

    rt = Runtime(store=store, router=router, promoter=promoter, drift=drift)
    return rt
