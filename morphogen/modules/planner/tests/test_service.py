"""The planner against a live record: the blast radius guard (T19, R5-32). A limit anomaly on podinfo's
frontend leads, over the map, to a step on the backend; the step's reach is the backend and everything that
depends on it (the frontend, and a gateway that connects to the frontend). Over the budget the plan is refused
before review and nothing is submitted; within it the plan goes to review as before.

  PGHOST=... PGUSER=<superuser> python3 tests/test_service.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "src"), str(ROOT / "morphogen" / "modules"),
                str(ROOT / "kernel" / "providers" / "validator-shacl")]
import importlib  # noqa: E402

from kk.lib import connect, run, submit  # noqa: E402
from planner.__main__ import one_pass  # noqa: E402
from planner.plan import CHECKSUM, DCT_TYPE, LIMIT_KIND, MAX, OA, PROP, RESULT  # noqa: E402
from morphogen import systems  # noqa: E402

install = importlib.import_module("install")
validator = importlib.import_module("validator.__main__")
DB = "kk_planner_test"
KKT = "https://w3id.org/knowledge-kernel/tosca#"
SEED, MAPPER = "urn:kk:agent:test-seed", "urn:kk:agent:test-mapper"
LAT = "urn:kk:property:latency-seconds-mean"
NODE = "urn:kk:node:podinfo:"


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="kk-planner-"))
    intent = tmp / "intent"
    shutil.copytree(ROOT / "morphogen" / "intent", intent)
    policy = intent / "policies" / "autonomy.yaml"

    def budget(n: int) -> None:
        p = yaml.safe_load(policy.read_text())
        p["guards"]["blast_radius_budget_slots"] = n
        policy.write_text(yaml.safe_dump(p, sort_keys=False))

    subprocess.run(["dropdb", "--if-exists", DB], check=True)
    install.install(DB, ["lane-autonomy", "planner"])
    url = f"dbname={DB}"
    with connect(url=url) as su:
        for role in ("t_planner_seed", "t_planner_mapper"):
            su.execute(f"do $$ begin if not exists (select 1 from pg_roles where rolname = '{role}') then "
                       f"create role {role} nologin; end if; end $$")
            su.execute(f"grant kk_agent to {role}")
        su.execute("set role kk_owner")
        su.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, 't_planner_seed', 'software', 's'), "
                   "(%s, 't_planner_mapper', 'software', 'm') on conflict do nothing", (SEED, MAPPER))

    def claim(s, p, o, q=None, **kw):
        c = {"op": "add_claim", "subject": s, "predicate": p, "object": o, "evidence_type": "deterministic",
             "references": [{"source_uri": "urn:test:planner"}], **kw}
        if q:
            c["qualifiers"] = q
        return c

    with connect("t_planner_seed", url) as seed, connect("t_planner_mapper", url) as mapper, \
            connect("kkm_planner", url) as pl, connect("kkm_validator", url) as val:
        def cs(conn, agent, key, ops):
            with conn.cursor() as cur, run(cur, "urn:kk:module:test-seed") as (rid, _):
                submit(cur, {"idempotency_key": key, "attributed_to": agent, "target_scope": "urn:kk:scope:default",
                             "ops": ops}, rid)
            validator.drain(val)

        def ids(subject):
            return [str(r[0]) for r in seed.execute("select id from api.claims where subject = %s", (subject,)).fetchall()]

        cs(mapper, MAPPER, "map", [claim(NODE + "frontend", KKT + "connectsTo", {"entity": NODE + "backend"}),
                                   claim(NODE + "gateway", KKT + "connectsTo", {"entity": NODE + "frontend"}),
                                   claim(NODE + "backend", KKT + "connectsTo", {"entity": NODE + "redis"})])
        cs(seed, SEED, "obs", [claim(NODE + "frontend", RESULT, {"value": {"@value": 0.31}}, {PROP: LAT}),
                               claim(NODE + "frontend", MAX, {"value": {"@value": 0.15}}, {PROP: LAT})])
        premises = ids(NODE + "frontend")
        premises = [i for i in premises if i not in
                    {str(r[0]) for r in seed.execute("select id from api.claims where predicate = %s", (KKT + "connectsTo",))}]
        a = "urn:kk:anomaly:test-frontend"
        cs(seed, SEED, "anomaly", [
            {"op": "add_claim", "subject": a, "predicate": DCT_TYPE, "object": {"entity": LIMIT_KIND},
             "evidence_type": "inferred", "derived_from": premises},
            {"op": "add_claim", "subject": a, "predicate": OA + "hasTarget", "object": {"entity": NODE + "frontend"},
             "evidence_type": "inferred", "derived_from": premises}])

        def plans():
            return pl.execute("select count(*) from api.change_sets where attributed_to = 'urn:kk:agent:planner'").fetchone()[0]

        budget(2)
        got = one_pass(pl, intent, "sandbox", [MAPPER])[a]
        check("none" in got and "blast radius budget of 2" in got["none"]
              and got["reach"] == [NODE + "backend", NODE + "frontend", NODE + "gateway"] and plans() == 0,
              "a step whose reach (the backend, the frontend calling it, the gateway calling that) is over the budget "
              "is refused before review; nothing is submitted")
        check(NODE + "redis" not in got["reach"], "what the step's node depends on is not in its reach, only what depends on it")

        p = yaml.safe_load(policy.read_text())
        del p["guards"]["blast_radius_budget_slots"]
        policy.write_text(yaml.safe_dump(p, sort_keys=False))
        got = one_pass(pl, intent, "sandbox", [MAPPER])[a]
        check(got.get("none", "").startswith("refused:") and plans() == 0, "no budget set: the guard fails closed")

        budget(3)
        got = one_pass(pl, intent, "sandbox", [MAPPER])[a]
        validator.drain(val)
        check("plan" in got and got["lane"] == "review" and plans() == 1, "within the budget the plan goes to review")
        with connect(url=url) as su:
            ops = su.execute("select ops from kernel.change_set where id = %s", (got["change_set"],)).fetchone()[0]
        result = [(o["object"]["value"]["@value"], (o.get("qualifiers") or {}).get(CHECKSUM)) for o in ops if o["predicate"] == RESULT]
        f = intent / "systems" / "podinfo" / "compose.yaml"
        want = systems.sha(systems.with_setting(f.read_text(), "backend", "PODINFO_RANDOM_DELAY_MAX", float(result[0][0]))[2])
        check(len(result) == 1 and result[0][1] == want,
              "the step names the sha256 of the compose file it yields, so only that file can run once approved (T26)")
    subprocess.run(["dropdb", "--if-exists", DB], check=True)
    shutil.rmtree(tmp)
    print("planner service checks passed")


if __name__ == "__main__":
    main()
