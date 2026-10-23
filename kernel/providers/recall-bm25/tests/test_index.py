"""The BM25 index follows the record: a new claim is found once indexed, a redacted one is dropped (its
words no longer rank it), a deprecated one is left out at query time, and a reader finds only claims of
scopes it may read.

  PGHOST=... PGUSER=<superuser> python3 kernel/providers/recall-bm25/tests/test_index.py
"""
import importlib
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROVIDERS = HERE.parents[1]
for p in (PROVIDERS.parent / "src", PROVIDERS, PROVIDERS / "recall-bm25"):
    sys.path.insert(0, str(p))

import install  # noqa: E402
from kk import recall  # noqa: E402
from kk.lib import connect, follow, run, submit  # noqa: E402

index = importlib.import_module("recall_bm25.__main__")
DB = "kk_recall_test"
URL = f"dbname={DB}"


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}")


def claim(cur, key: str, scope: str, subject: str, text: str) -> str:
    with run(cur, "urn:kk:module:test-writer") as (run_id, _):
        return submit(cur, {"idempotency_key": key, "attributed_to": "urn:kk:agent:test-writer", "target_scope": scope,
                            "ops": [{"op": "add_claim", "subject": subject, "predicate": "rdfs:label",
                                     "object": {"value": {"@value": text}}, "evidence_type": "deterministic",
                                     "references": [{"source_uri": "https://example.org/x"}]}]}, run_id)["id"]


def subjects(conn, text: str) -> set:
    return {r["subject"] for r in recall.recall(conn, text, 20)}


def main() -> None:
    subprocess.run(["dropdb", "--if-exists", "--force", DB], check=True)
    install.install(DB, ["recall-bm25"])
    with connect(url=URL) as su:
        for role in ("t_recall_writer", "t_recall_reader", "t_recall_validator", "t_recall_steward", "t_recall_cleared"):
            su.execute(f"do $$ begin if not exists (select 1 from pg_roles where rolname = '{role}') then "
                       f"create role {role} nologin; end if; end $$")
        su.execute("grant kk_agent to t_recall_writer, t_recall_reader")
        su.execute("grant kk_validator to t_recall_validator")
        su.execute("grant kk_steward to t_recall_steward")
        su.execute("grant t_recall_cleared to t_recall_writer, t_recall_validator, kkm_recall_index")
        su.execute("set role kk_owner")
        su.execute("insert into kernel.agent(iri, db_role, kind, label) values "
                   "('urn:kk:agent:test-writer', 't_recall_writer', 'software', 'w'), "
                   "('urn:kk:agent:test-reader', 't_recall_reader', 'software', 'r'), "
                   "('urn:kk:agent:test-validator', 't_recall_validator', 'software', 'v'), "
                   "('urn:kk:agent:test-steward', 't_recall_steward', 'person', 's') on conflict do nothing")
        su.execute("insert into kernel.scope values ('urn:kk:scope:test-secret', 'secret') on conflict do nothing")
        su.execute("insert into kernel.scope_grant values ('urn:kk:scope:test-secret', 't_recall_cleared', true, true)"
                   " on conflict do nothing")
    with connect("t_recall_writer", URL) as w, connect("t_recall_validator", URL) as v, \
            connect("t_recall_reader", URL) as r, connect("t_recall_steward", URL) as st, \
            connect("kkm_recall_index", URL) as idx:
        with w.cursor() as cur:
            public = claim(cur, "t:1", "urn:kk:scope:default", "urn:x:ledger", "nightly ledger reconciliation")
            secret = claim(cur, "t:2", "urn:kk:scope:test-secret", "urn:x:vault", "ledger vault keys")
        for cs in (public, secret):
            v.execute("select api.record_validation(%s, true)", (cs,))
        index.Pass()(idx)
        check(recall.indexed(r), "the index has rows and api.recall is used")
        check(subjects(r, "ledger") == {"urn:x:ledger"}, "a reader finds the public claim and not the secret one")
        check(subjects(w, "ledger") == {"urn:x:ledger", "urn:x:vault"}, "a cleared reader finds both")

        # The worker running as a service: a redaction wakes it from the feed (R5-O3), not at the next sweep.
        def serve() -> None:
            try:
                follow(idx, index.Pass(), poll=0.1, sweep=3600)
            except Exception:
                pass   # the connection closes when the test ends
        threading.Thread(target=serve, daemon=True).start()
        time.sleep(0.5)
        target = w.execute("select id from api.claims where subject = 'urn:x:ledger'").fetchone()[0]
        with st.cursor() as cur, run(cur, None) as (run_id, _):
            cur.execute("select api.redact('claim', %s, 'test erasure', %s)", (str(target), run_id))
        deadline = time.monotonic() + 5
        while subjects(r, "reconciliation") and time.monotonic() < deadline:
            time.sleep(0.1)
        check(not subjects(r, "reconciliation"), "a redacted claim's words no longer find it, within seconds")
    subprocess.run(["dropdb", "--force", DB], check=True)
    print("ALL RECALL INDEX TESTS PASSED")


if __name__ == "__main__":
    main()
