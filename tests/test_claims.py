"""Step 2: claims are bitemporal; create, change, close and query at two valid times."""

from datetime import UTC, datetime, timedelta

from morphogen.domain.ontology import Coupling, Slot, now
from morphogen.store import Query

T0 = datetime(2026, 10, 1, tzinfo=UTC)
T1 = T0 + timedelta(days=1)
T2 = T0 + timedelta(days=2)


def slot(role="db", **kw):
    base = dict(key="bp/db", role=role, name="db", status="hypothetical", provenance="asserted",
                source_event_id="e1", valid_from=T0, recorded_at=now())
    return Slot(**{**base, **kw})


def test_create_and_query(store):
    cs = store.upsert([slot()])
    assert cs.created.nodes == ["bp/db"]
    [s] = store.query(kind="Slot")
    assert (s.role, s.status, s.environment, s.level) == ("db", "hypothetical", "sandbox", "instance")


def test_same_content_is_a_noop(store):
    store.upsert([slot()])
    assert store.upsert([slot()]).empty


def test_change_closes_old_interval_and_opens_new(store):
    store.upsert([slot()])
    recorded_before = now()
    cs = store.upsert([slot(role="knowledge-store", valid_from=T1)])
    assert cs.changed.nodes == ["bp/db"]

    assert store.query(Query(kind="Slot", valid_at=T0 + timedelta(hours=1)))[0].role == "db"
    assert store.query(Query(kind="Slot", valid_at=T2))[0].role == "knowledge-store"
    # What did we believe about T2 before the change was recorded?
    then = store.query(Query(kind="Slot", valid_at=T2, recorded_at=recorded_before))
    assert [s.role for s in then] == ["db"]
    # Nothing was overwritten: original, closed copy, new version.
    assert len(store.history("bp/db")) == 3


def test_retire_keeps_history_and_hides_current(store):
    store.upsert([slot()])
    cs = store.retire([("bp/db", "hypothetical", "sandbox")], T1)
    assert cs.retired.nodes == ["bp/db"]
    assert store.query(kind="Slot") == []
    assert [s.role for s in store.query(Query(kind="Slot", valid_at=T0 + timedelta(hours=1)))] == ["db"]
    assert store.history("bp/db")[-1].valid_to == T1


def test_statuses_are_separate_claims(store):
    store.upsert([slot(), slot(status="observed", provenance="discovered", key="bp/db")])
    assert sorted(s.status for s in store.query(kind="Slot")) == ["hypothetical", "observed"]


def test_coupling_edges_reported(store):
    c = Coupling(key="bp/c1", coupling_type="call", source_port="bp/a.out", target_port="bp/b.in",
                 source_slot="a", target_slot="b", status="hypothetical", provenance="asserted",
                 source_event_id="e1", valid_from=T0, recorded_at=now())
    cs = store.upsert([c])
    assert cs.created.edges == ["bp/c1|from|bp/a.out", "bp/c1|to|bp/b.in"]
    cs = store.upsert([c.model_copy(update={"target_port": "bp/b.in2", "valid_from": T1})])
    assert cs.created.edges == ["bp/c1|to|bp/b.in2"] and cs.retired.edges == ["bp/c1|to|bp/b.in"]


def test_touch_tracks_freshness(store):
    store.touch(["k"], T0)
    store.touch(["k"], T1)
    store.touch(["k"], T0)
    assert store.last_seen(["k", "missing"]) == {"k": T1}
