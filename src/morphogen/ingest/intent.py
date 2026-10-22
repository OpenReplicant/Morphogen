"""Intent ingestor: intent.committed -> intended slot claims.

The promoter never writes the map; it publishes intent.committed and this
ingestor records what is now intended. Nothing becomes observed here: an
intended slot stays in drift until its traces arrive (invariant 7).
"""

from __future__ import annotations

from morphogen.domain.ontology import Provenance, Slot, Status, now
from morphogen.events import parse_time
from morphogen.store import ChangeSet, MapStore


class IntentIngestor:
    pipeline = "intent"
    types = ("intent.committed",)

    def run(self, event: dict, store: MapStore) -> ChangeSet:
        data = event["data"]
        env = data["environment"]
        claims = [
            Slot(key=f"intent/{data['target']}/{name}", role="intended", name=name,
                 provider_hint=data["proposal_id"], status=Status.INTENDED, environment=env,
                 provenance=Provenance.ASSERTED, confidence=0.6, source_event_id=event["id"],
                 valid_from=parse_time(event["time"]), recorded_at=now())
            for name in data["affected_slots"]
        ]
        return store.upsert(claims)
