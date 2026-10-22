"""Promoter: the only path from proposal to intent (invariants 2 and 3).

Evaluates each proposal against the autonomy policy and guards, waits for a
person where policy requires one, writes approved files under `intent/`,
commits them when `intent/` is its own git repository, and publishes
intent.committed. It never writes the map and never calls an orchestrator.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from morphogen import queries
from morphogen.domain.ontology import now
from morphogen.events import make, parse_time
from morphogen.promoter.policy import Policy
from morphogen.promoter.state import GovernanceState, MemoryGovernance, ProposalRecord
from morphogen.store import MapStore

log = logging.getLogger(__name__)
SLOT = "promoter"
AUTONOMOUS = ("auto", "auto_notify")


class Promoter:
    def __init__(self, intent_dir: str | Path, store: MapStore, publish: Callable[[dict], str],
                 state: GovernanceState | None = None, policy: Policy | None = None) -> None:
        self.intent_dir = Path(intent_dir).resolve()
        self.store = store  # read-only use: blast radius
        self.publish = publish  # submits an event to the intake
        self.state = state or MemoryGovernance()
        self.policy = policy or Policy.load(self.intent_dir / "policies")

    # -- event handlers ------------------------------------------------------

    def on_proposal(self, event: dict) -> None:
        if self.state.get(event["id"]):
            return  # duplicate delivery
        data = event["data"]
        p = ProposalRecord(
            id=event["id"], target=data["target"], risk=data["risk"], event=event,
            expires_at=parse_time(data["expires_at"]), received_at=now(),
            affected_slots=data["change"].get("affected_slots", []),
        )
        target = self.state.get_target(p.target)
        p.decision = self.policy.decide(target.autonomy, p.risk)
        blocked = self._guards(p)
        if blocked:
            p.state, p.note = blocked
        elif p.decision in AUTONOMOUS:
            self.state.put(p)
            self._commit(p, decided_by=f"policy:{target.autonomy}")
            return
        else:
            p.note = ("awaiting a person" if p.decision == "approve"
                      else f"reported at {target.autonomy}; a person may approve")
        self.state.put(p)

    def on_decision(self, event: dict) -> None:
        data = event["data"]
        p = self.state.get(data["proposal_id"])
        if p is None or p.state != "pending":
            log.warning("decision for unknown or settled proposal %s", data["proposal_id"])
            return
        if not str(event["source"]).startswith("person:"):
            p.note = f"ignored decision from {event['source']}: approvals need a person"
            self.state.put(p)
            return
        if data["decision"] == "reject":
            p.state, p.decided_by, p.note = "rejected", event["source"], data.get("reason")
            self.state.put(p)
            return
        blocked = self._guards(p)  # preconditions re-checked before commit
        if blocked:
            p.state, p.note = blocked
            self.state.put(p)
            return
        p.state = "approved"
        self.state.put(p)
        self._commit(p, decided_by=event["source"])

    # -- guards --------------------------------------------------------------

    def _guards(self, p: ProposalRecord) -> tuple[str, str] | None:
        """(state, note) when a guard stops the proposal now; None to proceed."""
        t = now()
        if self.policy.killed() or self.state.get_target(p.target).kill_switch:
            return ("pending", "kill switch on")
        if p.expires_at <= t:
            return ("expired", "expired before commit")
        env = p.event["data"]["change"].get("environment", "sandbox")
        radius = queries.blast_radius(self.store, p.affected_slots, env)
        touched = len(p.affected_slots) + len(radius["affected"])
        if touched > self.policy.blast_budget:
            note = f"blast radius {touched} slots over budget {self.policy.blast_budget}; split it"
            return ("rejected", note)
        committed = [q for q in self.state.list(p.target, "committed") if q.committed_at]
        if sum(q.committed_at > t - timedelta(hours=1) for q in committed) >= self.policy.max_per_hour:
            return ("pending", "rate limit: too many changes this hour")
        cool = t - self.policy.cooldown
        hot = {s for q in committed if q.committed_at > cool for s in q.affected_slots} \
            & set(p.affected_slots)
        if hot:
            return ("pending", f"cooldown on {sorted(hot)}")
        return None

    # -- commit --------------------------------------------------------------

    def _write_files(self, files: list[dict]) -> list[str]:
        written = []
        for f in files:
            path = (self.intent_dir / f["path"]).resolve()
            if not path.is_relative_to(self.intent_dir) or path.is_relative_to(self.intent_dir / "policies"):
                raise ValueError(f"refusing to write outside intent/ or into policies/: {f['path']}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f["content"])
            written.append(str(path.relative_to(self.intent_dir)))
        return written

    def _git_commit(self, paths: list[str], message: str) -> str | None:
        """Commit when intent/ is the top of its own work tree; otherwise leave files uncommitted."""
        top = subprocess.run(["git", "-C", str(self.intent_dir), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=False)
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != self.intent_dir:
            return None
        git = ["git", "-C", str(self.intent_dir), "-c", "user.name=morphogen-promoter",
               "-c", "user.email=promoter@morphogen.invalid"]
        subprocess.run([*git, "add", "--", *paths], check=True, capture_output=True)
        unchanged = subprocess.run([*git, "diff", "--cached", "--quiet", "--", *paths],
                                   check=False).returncode == 0
        if not unchanged:  # identical content is already intended; HEAD records it
            subprocess.run([*git, "commit", "-m", message, "--", *paths], check=True, capture_output=True)
        return subprocess.run([*git, "rev-parse", "HEAD"], check=True, capture_output=True,
                              text=True).stdout.strip()

    def _commit(self, p: ProposalRecord, decided_by: str) -> None:
        change = p.event["data"]["change"]
        env = change.get("environment", "sandbox")
        try:
            paths = self._write_files(change["files"])
            sha = self._git_commit(paths, f"proposal:{p.id} {p.event['data']['summary']}")
        except Exception as e:
            log.exception("commit failed for %s", p.id)
            p.state, p.note = "rejected", f"commit failed: {e}"
            self.state.put(p)
            return
        p.state, p.decided_by, p.commit_sha, p.committed_at = "committed", decided_by, sha, now()
        self.state.put(p)
        self.publish(make("intent.committed", "promoter", {
            "proposal_id": p.id, "target": p.target, "environment": env, "commit": sha,
            "files": paths, "affected_slots": p.affected_slots, "decided_by": decided_by,
        }, environment=env, causationid=p.id, correlationid=p.id))


def expire(state: GovernanceState, at: datetime | None = None) -> list[str]:
    """Mark pending proposals past their expiry; returns their ids."""
    t = at or now()
    out = []
    for p in state.list(state="pending"):
        if p.expires_at <= t:
            p.state, p.note = "expired", "expired while pending"
            state.put(p)
            out.append(p.id)
    return out
