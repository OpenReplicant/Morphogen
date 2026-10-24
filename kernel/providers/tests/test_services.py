"""End to end: the validator, quote verifier and belief model as services on one record.

An extractor submits two extracted claims citing a file, one quoting it and one with a made-up quote.
Each service runs one pass under its own role, and its change sets go through validation like any other:
the verifier supports one claim and refutes the other, the belief model caps the refuted one (D-67), and
every applied change set shows up in the change feed in commit order.

  PGHOST=... PGUSER=<superuser> python3 kernel/providers/tests/test_services.py   (needs psycopg, the contract requirements)
"""
import importlib
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from psycopg.types.json import Jsonb

HERE = Path(__file__).resolve().parent
PROVIDERS = HERE.parent
for p in (PROVIDERS.parent / "src", PROVIDERS / "validator-shacl", PROVIDERS / "belief-corroboration",
          PROVIDERS / "verifier-quotes", PROVIDERS / "evaluator", PROVIDERS):
    sys.path.insert(0, str(p))

from kk.lib import connect, feed_after, feed_head, feed_since, follow, resume, run, submit  # noqa: E402
import install  # noqa: E402

validator = importlib.import_module("validator.__main__")
belief = importlib.import_module("belief_corroboration.__main__")
quotes = importlib.import_module("verifier_quotes.__main__")
evaluator = importlib.import_module("evaluator.__main__")

DB = "kk_services_test"
EXTRACTOR = "urn:kk:agent:test-extractor"


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}")


def main() -> None:
    subprocess.run(["dropdb", "--if-exists", DB], check=True)
    install.install(DB, ["validator-shacl", "verifier-quotes", "belief-corroboration", "evaluator"])
    url = f"dbname={DB}"
    with connect(url=url) as su:
        su.execute("do $$ begin if not exists (select 1 from pg_roles where rolname = 't_services_extractor') then "
                   "create role t_services_extractor nologin; end if; end $$")
        su.execute("grant kk_agent to t_services_extractor")
        su.execute("set role kk_owner")
        su.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, 't_services_extractor', "
                   "'software', 'Test extractor') on conflict do nothing", (EXTRACTOR,))
        # dqv:value, as the dqv pack would approve it (the pack loader is not ported yet)
        su.execute("insert into kernel.prefix values ('dqv', 'http://www.w3.org/ns/dqv#') on conflict do nothing")
        su.execute("""select kernel.install_ops('test:dqv-value', 'urn:kk:scope:vocab', '[{"op": "add_claim",
                      "subject": "dqv:value", "predicate": "rdf:type", "object": {"entity": "owl:DatatypeProperty"},
                      "evidence_type": "deterministic", "references": [{"source_uri": "https://www.w3.org/TR/vocab-dqv/"}]}]')""")

    root = Path(tempfile.mkdtemp())
    (root / "README.md").write_text("The billing service sends invoices every night.\n")
    ops = [{"op": "add_claim", "subject": f"urn:x:{name}", "predicate": "rdfs:label",
            "object": {"value": {"@value": name}}, "evidence_type": "extracted",
            "references": [{"source_uri": "file:README.md", "quote": quote}]}
           for name, quote in (("good", "sends invoices every night"), ("bad", "sends invoices every hour"))]

    with connect("t_services_extractor", url) as ex, connect("kkm_validator", url) as val, \
            connect("kkm_verifier_quotes", url) as ver, connect("kkm_belief", url) as bel:
        with ex.cursor() as cur, run(cur, "urn:kk:module:test-extractor") as (run_id, _):
            cs = submit(cur, {"idempotency_key": "services:claims", "attributed_to": EXTRACTOR,
                              "target_scope": "urn:kk:scope:default", "ops": ops}, run_id)
        check(cs["status"] == "submitted", "an extractor's change set starts as submitted")
        check(validator.drain(val) == 1, "the validator judges the submitted change set")
        ids = dict(ex.execute("select subject, id from api.claims where change_set = %s", (cs["id"],)).fetchall())
        check(len(ids) == 2, "valid claims are applied")

        follow(ver, quotes.Pass(Path(tempfile.mkdtemp()), root), once=True)
        validator.drain(val)
        verdicts = dict(ex.execute("select claim_id, verdict from api.verifications").fetchall())
        check(verdicts.get(ids["urn:x:good"]) == "supported", "a quote found in its source is supported")
        check(verdicts.get(ids["urn:x:bad"]) == "refuted", "a made-up quote is refuted")

        follow(bel, belief.Pass(), once=True)
        validator.drain(val)
        got = dict(ex.execute("select id, belief from api.claims").fetchall())
        check(abs(got[ids["urn:x:good"]] - 0.5) < 1e-4, "one source gives belief 0.5")
        check(abs(got[ids["urn:x:bad"]] - 0.1) < 1e-4, "a refuted claim is capped at 0.1")

        mine = [r[0] for r in val.execute(   # a validator sees every change set in scopes it may read
            "select id from kernel.change_set where status = 'applied' and attributed_to <> 'urn:kk:agent:kernel' "
            "order by applied_at").fetchall()]
        fed = [e["change_set_id"] for e in feed_after(ex, 0) if e["change_set_id"] in mine]
        # claims, verifications, then beliefs per scope (the bootstrap vocabulary is scored too)
        check(fed == mine and len(fed) == 4, "claims, verifications and beliefs reach the feed in commit order")

        follow(bel, belief.Pass(), once=True)
        check(validator.drain(val) == 0, "a second belief pass with nothing new submits nothing")

    # The evaluator records a run file's scores; the same file again is a no-op, a changed one supersedes.
    store, runs = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
    (runs / "r1.json").write_text('{"split": "dev", "accuracy": 0.8, "models": {"m:free": 3}}')
    import os
    os.environ.update(PGDATABASE=DB, DATABASE_URL=url)
    for _ in range(2):
        evaluator.main(["--suite", "demo", "--artifacts", str(store), str(runs / "r1.json")])
    with connect("kkm_validator", url) as val:
        validator.drain(val)
    with connect("t_services_extractor", url) as ex:
        score = ex.execute("select (object_value->>'@value')::float, status, belief is null from api.claims "
                           "where subject = 'urn:kk:eval:demo:r1' and predicate like '%dqv#value'").fetchall()
        check(score == [(0.8, "normal", True)], "the evaluator records one observed score per number, once")
    (runs / "r1.json").write_text('{"split": "dev", "accuracy": 0.9}')
    evaluator.main(["--suite", "demo", "--artifacts", str(store), str(runs / "r1.json")])
    with connect("kkm_validator", url) as val:
        validator.drain(val)
    with connect("t_services_extractor", url) as ex:
        score = sorted(ex.execute("select (object_value->>'@value')::float, status from api.claims "
                                  "where subject = 'urn:kk:eval:demo:r1' and predicate like '%dqv#value'").fetchall())
        check(score == [(0.8, "deprecated"), (0.9, "normal")], "a changed run file supersedes its earlier scores")

    # A consumer asleep until its sweep wakes when the feed moves (polling api.feed, not NOTIFY).
    steps = []
    waker = connect("kkm_belief", url)

    def consume() -> None:
        try:
            follow(waker, lambda c: steps.append(1), poll=0.1, sweep=3600)
        except Exception:
            pass   # the connection is closed when the test ends
    threading.Thread(target=consume, daemon=True).start()
    time.sleep(0.5)
    with connect("t_services_extractor", url) as ex, connect("kkm_validator", url) as val:
        with ex.cursor() as cur, run(cur, "urn:kk:module:test-extractor") as (run_id, _):
            submit(cur, {"idempotency_key": "services:wake", "attributed_to": EXTRACTOR,
                         "target_scope": "urn:kk:scope:default",
                         "ops": [{"op": "add_entity", "iri": "urn:x:wake"}]}, run_id)
        validator.drain(val)
    deadline = time.monotonic() + 5
    while len(steps) < 2 and time.monotonic() < deadline:
        time.sleep(0.1)
    check(len(steps) == 2, "a feed consumer wakes when a change set is applied")
    waker.close()

    # A durable cursor (R5-18, T15): the feed seq in the outputs of the last succeeded run of a module.
    CURSOR = "urn:kk:module:test-cursor"
    with connect("t_services_extractor", url) as ex:
        check(resume(ex, CURSOR) == 0, "no run of the module yet: the cursor is 0")
        with ex.cursor() as cur:
            with run(cur, CURSOR) as (_, out):
                out["feed_seq"] = 5
            try:
                with run(cur, CURSOR) as (_, out):
                    out["feed_seq"] = 9
                    raise RuntimeError("failed after reading")
            except RuntimeError:
                pass
            cur.execute("select api.start_run(%s, null, '[]', '{}')", (CURSOR,))   # left running, as by a crash
            with run(cur, "urn:kk:module:test-other") as (_, out):
                out["feed_seq"] = 99
        check(resume(ex, CURSOR) == 5, "a failed or unfinished run, or another module's, does not move it")
        label = "http://www.w3.org/2000/01/rdf-schema#label"
        reached, entries = feed_since(ex, 0, {label}, page=1)
        made = ex.execute("select change_set, array_agg(id::text) from api.claims where predicate = %s "
                          "and subject like 'urn:x:%%' group by 1", (label,)).fetchall()
        check(reached == feed_head(ex) and len(made) == 1
              and [t for c, t in entries if c == made[0][0]] == [set(made[0][1])],
              "feed_since reads every page to the head and names each entry's change set and claims")
        check(feed_since(ex, reached, {label}) == (reached, []), "nothing after the head: the cursor stays")

    subprocess.run(["dropdb", "--force", DB], check=True)
    print("ALL SERVICE TESTS PASSED")


if __name__ == "__main__":
    main()
