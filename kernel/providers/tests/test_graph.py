"""Dependency reasoning (kk.graph, T19): the packs make kkt:connectsTo and kkt:hostedOn subproperties of
kkt:dependsOn, so a closure over dependsOn follows all three; it follows chains, stops at cycles, runs
backwards (who depends on a node), keeps to the agents asked for, and leaves out withdrawn edges.

  PGHOST=... PGUSER=<superuser> python3 kernel/providers/tests/test_graph.py
"""
import importlib
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROVIDERS = HERE.parent
for p in (PROVIDERS.parent / "src", PROVIDERS / "validator-shacl", PROVIDERS):
    sys.path.insert(0, str(p))

from kk import graph  # noqa: E402
from kk.lib import connect, run, submit  # noqa: E402
import install  # noqa: E402

validator = importlib.import_module("validator.__main__")

DB = "kk_graph_test"
KKT = "https://w3id.org/knowledge-kernel/tosca#"
MAPPER, OTHER = "urn:kk:agent:test-mapper", "urn:kk:agent:test-other"


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def pure() -> None:
    e = [("a", "b", "1"), ("b", "c", "2"), ("c", "a", "3"), ("a", "c", "4"), ("d", "b", "5")]
    check(graph.closure(e, "a") == {"b": ["1"], "c": ["4"]}, "the shortest path to each node, the start left out")
    check(graph.closure(e, "c", reverse=True) == {"a": ["4"], "b": ["2"], "d": ["2", "5"]},
          "backwards: who depends on a node, through others")
    check(graph.closure(e, "x") == {}, "a node with no edges reaches nothing")
    check(graph.closure([("a", "b", "9"), ("a", "b", "1")], "a") == {"b": ["1"]}, "ties break the same way every time")


def main() -> None:
    pure()
    subprocess.run(["dropdb", "--if-exists", DB], check=True)
    install.install(DB, ["validator-shacl", "pack-loader"])
    url = f"dbname={DB}"
    with connect(url=url) as su:
        for role in ("t_graph_mapper", "t_graph_other", "t_graph_steward"):
            su.execute(f"do $$ begin if not exists (select 1 from pg_roles where rolname = '{role}') then "
                       f"create role {role} nologin; end if; end $$")
            su.execute(f"grant kk_agent to {role}")
        su.execute("grant kk_steward to t_graph_steward")
        su.execute("set role kk_owner")
        su.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, 't_graph_mapper', 'software', 'm'), "
                   "(%s, 't_graph_other', 'software', 'o'), ('urn:kk:agent:test-steward', 't_graph_steward', 'person', 's') "
                   "on conflict do nothing", (MAPPER, OTHER))

    def edge(s, p, o):
        return {"op": "add_claim", "subject": f"urn:x:{s}", "predicate": KKT + p, "object": {"entity": f"urn:x:{o}"},
                "evidence_type": "deterministic", "references": [{"source_uri": "urn:test:map"}]}

    with connect("t_graph_mapper", url) as m, connect("t_graph_other", url) as o, connect("kkm_validator", url) as val, \
            connect("t_graph_steward", url) as st:
        def cs(conn, agent, key, ops):
            with conn.cursor() as cur, run(cur, "urn:kk:module:test-map") as (rid, _):
                submit(cur, {"idempotency_key": key, "attributed_to": agent, "target_scope": "urn:kk:scope:default",
                             "ops": ops}, rid)
            validator.drain(val)

        with m.cursor() as cur:
            props = graph.subproperties(cur, graph.DEPENDS_ON)
        check({graph.DEPENDS_ON, KKT + "connectsTo", KKT + "hostedOn"} <= props,
              "connectsTo and hostedOn are subproperties of dependsOn, read from the packs in the record")
        cs(m, MAPPER, "map", [edge("web", "connectsTo", "api"), edge("api", "hostedOn", "vm"),
                              edge("vm", "dependsOn", "web"), edge("api", "connectsTo", "old")])
        cs(o, OTHER, "other", [edge("batch", "connectsTo", "api")])
        old = m.execute("select id::text from api.claims where object_entity = 'urn:x:old'").fetchone()[0]
        cs(m, MAPPER, "drop-old", [{"op": "set_status", "claim": old, "status": "deprecated", "expect_status": "normal",
                                    "reason": "retracted"}])
        with m.cursor() as cur:
            mine = graph.edges(cur, agents=[MAPPER])
            every = graph.edges(cur)
        down = graph.closure(mine, "urn:x:web")
        check(set(down) == {"urn:x:api", "urn:x:vm"} and len(down["urn:x:vm"]) == 2,
              "forward through connectsTo then hostedOn, the cycle back to web closed, the withdrawn edge left out")
        up = graph.closure(every, "urn:x:api", reverse=True)
        check(set(up) == {"urn:x:web", "urn:x:vm", "urn:x:batch"}, "backwards: everything that depends on api")
        check("urn:x:batch" not in graph.closure(mine, "urn:x:api", reverse=True),
              "edges kept to the agents asked for")

        # A redacted edge is withdrawn too; so is a subproperty whose declaration is withdrawn.
        batch = m.execute("select id::text from api.claims where subject = 'urn:x:batch'").fetchone()[0]
        with st.cursor() as cur, run(cur, None) as (rid, _):
            cur.execute("select api.redact('claim', %s, 'test erasure', %s)", (batch, rid))
        with m.cursor() as cur:
            check("urn:x:batch" not in graph.closure(graph.edges(cur), "urn:x:api", reverse=True), "a redacted edge is left out")
        hosted = m.execute("select id::text from api.claims where subject = %s and predicate = %s",
                           (KKT + "hostedOn", graph.SUBPROPERTY)).fetchone()[0]
        with m.cursor() as cur, run(cur, "urn:kk:module:test-map") as (rid, _):
            submit(cur, {"idempotency_key": "drop-hosted", "attributed_to": MAPPER, "target_scope": "urn:kk:scope:vocab",
                         "ops": [{"op": "set_status", "claim": hosted, "status": "deprecated", "expect_status": "normal",
                                  "reason": "retracted"}]}, rid)
        validator.drain(val)
        with m.cursor() as cur:
            props = graph.subproperties(cur, graph.DEPENDS_ON)
            down = graph.closure(graph.edges(cur, agents=[MAPPER]), "urn:x:web")
        check(KKT + "hostedOn" not in props and set(down) == {"urn:x:api"},
              "a withdrawn subPropertyOf declaration: hostedOn is no longer a dependency, and its edges drop out")
    subprocess.run(["dropdb", "--if-exists", DB], check=True)
    print("graph checks passed")


if __name__ == "__main__":
    main()
