"""Proposal ingestor: proposal.created -> hypothetical Hypothesis and Prediction claims.

The proposal itself is governance state (the promoter's); the map records what
it claims about the world so verification can compare predictions later.
"""

from __future__ import annotations

from morphogen.domain.ontology import Claim, Hypothesis, Prediction, Provenance, Status, now
from morphogen.events import parse_time
from morphogen.store import ChangeSet, MapStore


def to_claims(event: dict) -> list[Claim]:
    data = event["data"]
    common = dict(status=Status.HYPOTHETICAL, environment=event.get("environment", "sandbox"),
                  provenance=Provenance.ASSERTED, confidence=0.3, source_event_id=event["id"],
                  valid_from=parse_time(event.get("validtime", event["time"])), recorded_at=now())
    h = Hypothesis(key=f"proposal/{event['id']}/hypothesis", statement=data["hypothesis"],
                   proposal_event_id=event["id"], **common)
    preds = [
        Prediction(key=f"proposal/{event['id']}/prediction/{i}", hypothesis=h.key,
                   observation=p["observation"], comparison=p["comparison"], value=p.get("value"),
                   window=p["window"], **common)
        for i, p in enumerate(data["predictions"])
    ]
    return [h, *preds]


class ProposalIngestor:
    pipeline = "proposals"
    types = ("proposal.created",)

    def run(self, event: dict, store: MapStore) -> ChangeSet:
        return store.upsert(to_claims(event))
