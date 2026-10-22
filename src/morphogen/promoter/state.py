"""Governance state: proposals and targets. Owned by the promoter, not graph data."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime

STATES = ("pending", "approved", "rejected", "expired", "committed", "verified", "rolled_back")


@dataclass
class ProposalRecord:
    id: str
    target: str
    risk: str
    event: dict
    expires_at: datetime
    received_at: datetime
    state: str = "pending"
    decision: str | None = None  # what policy said: report | approve | auto | auto_notify
    note: str | None = None
    decided_by: str | None = None
    commit_sha: str | None = None
    committed_at: datetime | None = None
    affected_slots: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("event")
        return d


@dataclass
class TargetRecord:
    id: str
    autonomy: str = "L0"
    kill_switch: bool = False


class GovernanceState(ABC):
    @abstractmethod
    def get_target(self, target: str) -> TargetRecord: ...

    @abstractmethod
    def put_target(self, t: TargetRecord) -> None: ...

    @abstractmethod
    def get(self, proposal_id: str) -> ProposalRecord | None: ...

    @abstractmethod
    def put(self, p: ProposalRecord) -> None: ...

    @abstractmethod
    def list(self, target: str | None = None, state: str | None = None) -> list[ProposalRecord]: ...


class MemoryGovernance(GovernanceState):
    def __init__(self) -> None:
        self.targets: dict[str, TargetRecord] = {}
        self.proposals: dict[str, ProposalRecord] = {}
        self._lock = threading.RLock()

    def get_target(self, target: str) -> TargetRecord:
        return self.targets.get(target) or TargetRecord(target)

    def put_target(self, t: TargetRecord) -> None:
        self.targets[t.id] = t

    def get(self, proposal_id: str) -> ProposalRecord | None:
        return self.proposals.get(proposal_id)

    def put(self, p: ProposalRecord) -> None:
        with self._lock:
            self.proposals[p.id] = p

    def list(self, target: str | None = None, state: str | None = None) -> list[ProposalRecord]:
        return sorted((p for p in self.proposals.values()
                       if (target is None or p.target == target) and (state is None or p.state == state)),
                      key=lambda p: p.received_at)


class PostgresGovernance(GovernanceState):
    """Governance tables from deploy/postgres/init.sql, opened with the promoter role."""

    COLS = ("id", "target", "risk", "event", "state", "decision", "note", "decided_by",
            "commit_sha", "committed_at", "affected_slots", "received_at", "expires_at")

    def __init__(self, dsn: str) -> None:
        import psycopg2
        import psycopg2.extras

        self._extras = psycopg2.extras
        self.conn = psycopg2.connect(dsn)
        self.conn.autocommit = True
        self._lock = threading.RLock()

    def _rows(self, sql: str, args=()) -> list[dict]:
        with self._lock, self.conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
            cur.execute(sql, args)
            return [dict(r) for r in cur.fetchall()] if cur.description else []

    def get_target(self, target: str) -> TargetRecord:
        rows = self._rows("SELECT id, autonomy, kill_switch FROM governance.targets WHERE id=%s", (target,))
        return TargetRecord(**rows[0]) if rows else TargetRecord(target)

    def put_target(self, t: TargetRecord) -> None:
        self._rows("INSERT INTO governance.targets (id, autonomy, kill_switch) VALUES (%s, %s, %s)"
                   " ON CONFLICT (id) DO UPDATE SET autonomy=excluded.autonomy,"
                   " kill_switch=excluded.kill_switch", (t.id, t.autonomy, t.kill_switch))

    def _record(self, r: dict) -> ProposalRecord:
        return ProposalRecord(**{k: r[k] for k in self.COLS})

    def get(self, proposal_id: str) -> ProposalRecord | None:
        rows = self._rows(f"SELECT {', '.join(self.COLS)} FROM governance.proposals WHERE id=%s",
                          (proposal_id,))
        return self._record(rows[0]) if rows else None

    def put(self, p: ProposalRecord) -> None:
        vals = asdict(p)
        vals["event"] = self._extras.Json(vals["event"])
        vals["affected_slots"] = self._extras.Json(vals["affected_slots"])
        updates = ", ".join(f"{c}=excluded.{c}" for c in self.COLS if c != "id")
        self._rows(f"INSERT INTO governance.proposals ({', '.join(self.COLS)})"
                   f" VALUES ({', '.join('%(' + c + ')s' for c in self.COLS)})"
                   f" ON CONFLICT (id) DO UPDATE SET {updates}", vals)

    def list(self, target: str | None = None, state: str | None = None) -> list[ProposalRecord]:
        rows = self._rows(
            f"SELECT {', '.join(self.COLS)} FROM governance.proposals"
            " WHERE (%(t)s::text IS NULL OR target=%(t)s) AND (%(s)s::text IS NULL OR state=%(s)s)"
            " ORDER BY received_at", {"t": target, "s": state})
        return [self._record(r) for r in rows]
