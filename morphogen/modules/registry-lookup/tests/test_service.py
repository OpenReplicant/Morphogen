"""Catalog lookup against a live database (R5-30): a build request answered from provider catalogs, a pinned one
becoming an experiment the sandbox lists, an unpinned one offered and never run, an enforced licence rule
withholding only the offer; a search of a component set outside software recording its entries with nothing
offered; each request answered once.

  PGHOST=... PGUSER=<superuser> python3 tests/test_service.py
"""
import importlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "src"), str(ROOT / "morphogen" / "modules"),
                str(ROOT / "morphogen" / "modules" / "sandbox"), str(ROOT / "morphogen" / "modules" / "planner"), str(ROOT / "kernel" / "providers" / "validator-shacl")]
from kk.lib import connect, run, submit  # noqa: E402
from morphogen.experiments import BUILD, DCT, OA, experiment_id, tree_hash  # noqa: E402

from registry_lookup.__main__ import AGENT, KKT, one_pass, search  # noqa: E402

install = importlib.import_module("install")
validator = importlib.import_module("validator.__main__")
sandbox = importlib.import_module("sandbox.__main__")
planner = importlib.import_module("planner.__main__")
DB = "kk_registry_lookup_test"
FULFILLS = KKT + "fulfills"
RECENT = "urn:kk:provider:anomaly-recent"
MAX = "https://www.irit.fr/recherches/MELODI/ontologies/BBO#maxValue"


def check(cond, msg):
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def request(cur, iri, target="urn:kk:provider:anomaly", slot="urn:kk:slot:analyser"):
    claim = lambda p, o: {"op": "add_claim", "subject": iri, "predicate": p, "object": o, "evidence_type": "testimony",  # noqa: E731
                          "references": [{"source_uri": "urn:kk:test:registry-lookup"}]}
    with run(cur, "urn:kk:module:planner") as (rid, _):
        return submit(cur, {"idempotency_key": f"test:{iri}", "attributed_to": "urn:kk:agent:planner", "target_scope": "urn:kk:scope:default",
                     "ops": [claim(DCT + "type", {"entity": BUILD}), claim(OA + "hasTarget", {"entity": target}),
                             claim(DCT + "subject", {"entity": slot}),
                             claim(OA + "bodyValue", {"value": {"@value": "Make each pass read only the windows it compares."}})]}, rid)


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    git = lambda repo, *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],  # noqa: E731
                                          check=True, capture_output=True, text=True).stdout.strip()
    # A provider repository, pinned at its first commit; the second commit must never be what runs.
    repo = tmp / "providers"
    shutil.copytree(ROOT / "morphogen" / "tests" / "fixtures" / "analyser" / "anomaly-recent", repo / "anomaly-recent",
                    ignore=shutil.ignore_patterns("__pycache__"))
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "one")
    first = git(repo, "rev-parse", "HEAD")
    tree_sha = tree_hash(repo / "anomaly-recent")
    (repo / "anomaly-recent" / "LATER").write_text("after the pin\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "two")

    intent = tmp / "intent"
    shutil.copytree(ROOT / "morphogen" / "intent", intent)
    shutil.rmtree(intent / "catalogs")
    (intent / "catalogs").mkdir()
    cats = {
        "mine": {"kind": "providers", "label": "Our providers", "source": {"git": str(repo), "commit": first, "path": "."}},
        "local": {"kind": "providers", "source": {"dir": "morphogen/tests/fixtures/analyser"}},
        "strict": {"kind": "providers", "source": {"git": str(repo), "commit": first, "path": "."},
                   "rules": {"licences": {"enforce": True, "allow": ["MIT"]}}},
        "bike-parts": {"kind": "components", "label": "Bicycle parts", "components": [
            {"id": "chainring-52t", "label": "Chainring, 52 teeth", "kind": "part", "licence": "proprietary",
             "properties": {"material": "aluminium 7075", "teeth": 52}},
            {"id": "chain-11s", "label": "Chain, 11-speed", "kind": "part"},
            {"id": "urn:kk:provider:anomaly", "kind": "provider", "catalog": "mine", "label": "a spoofed provider"}]},
    }
    for name, c in cats.items():
        (intent / "catalogs" / f"{name}.yaml").write_text(yaml.safe_dump(c, sort_keys=False))
    git(intent, "init", "-q")
    git(intent, "add", "-A")
    git(intent, "commit", "-qm", "intent")

    subprocess.run(["dropdb", "--if-exists", DB], check=True)
    install.install(DB, install.modules())
    url = f"dbname={DB}"
    with connect("kkm_planner", url) as pl, connect("kkm_validator", url) as val, \
            connect("kkm_registry_lookup", url) as rl, connect("kkm_sandbox", url) as sbx, connect(url=url) as su, \
            connect("kkm_evaluator", url) as ev:
        planner_conn = pl
        with pl.cursor() as cur:
            request(cur, "urn:kk:request:c1")
        validator.drain(val)
        report = one_pass(rl, intent)
        validator.drain(val)
        answers = {a["catalog"]: a for a in report["urn:kk:request:c1"]["answers"]}
        check(report["urn:kk:request:c1"]["status"] == "answered" and set(answers) == {"local", "mine", "strict"},
              "a build request is answered from every provider catalog")

        exp_id = experiment_id(f"urn:kk:request:c1|{RECENT}")
        exp = intent / "experiments" / exp_id
        check(answers["mine"].get("experiment") == exp_id and (exp / "anomaly-recent" / "provider.yaml").exists()
              and not (exp / "anomaly-recent" / "LATER").exists()
              and yaml.safe_load((exp / "experiment.yaml").read_text())["strategy"] == "catalog",
              "a pinned provider becomes an experiment holding the pinned commit's content, not a later one")
        check(git(intent, "log", "-1", "--format=%s").startswith("request:urn:kk:request:c1 experiment:")
              and git(intent, "status", "--porcelain") == "", "one commit to intent, naming the request")
        check(sandbox.pending(sbx, ["urn:kk:agent:builder", AGENT]) == [exp_id],
              "the sandbox lists the catalog's candidate as it lists the builder's")
        check(answers["local"]["offered"] and "not pinned" in answers["local"].get("refused", "")
              and "experiment" not in answers["local"], "an unpinned provider is offered, never run")
        check(not answers["strict"]["offered"] and "experiment" not in answers["strict"],
              "an enforced licence rule withholds the offer")

        def claims_of(cs):
            return su.execute("""select c.predicate, c.object_entity, c.evidence_type, c.qualifiers, c.object_value
                                 from api.claims c join kernel.claim c2 on c2.id = c.id where c2.change_set = %s""",
                              (cs,)).fetchall()
        mine, strict = claims_of(answers["mine"]["change_set"]), claims_of(answers["strict"]["change_set"])
        check(any(p == FULFILLS and o == "urn:kk:slot:analyser" and ev == "inferred" for p, o, ev, _, _ in mine),
              "the offer is recorded: the provider kkt:fulfills the slot, inferred from the request")
        check(not any(p == FULFILLS for p, *_ in strict)
              and any(p == KKT + "propertyValue" and (q or {}).get(KKT + "propertyName") == "rule:licences"
                      and str((v or {}).get("@value", "")).startswith("fails") for p, _, _, q, v in strict),
              "under the enforced rule the entry is still recorded, with the verdict, and only the offer is withheld")
        check(one_pass(rl, intent) == {}, "a request is answered once")

        def value_of(rows_, name):
            return [(q or {}).get(DCT + "isPartOf") for p, _, _, q, v in rows_
                    if p == KKT + "propertyValue" and (q or {}).get(KKT + "propertyName") == name]
        check(value_of(mine, "rule:licences") == ["urn:kk:catalog:mine"] and value_of(strict, "rule:licences") == ["urn:kk:catalog:strict"]
              and value_of(mine, "slot") == ["urn:kk:catalog:mine"],
              "each value is qualified by the catalog that gave it (two catalogs disagree about one provider without conflict); "
              "the slots the entry says it fills are recorded")
        ref = su.execute("""select r.source_uri from api.claim_references r join api.claims c on c.id = r.claim_id
                            join kernel.claim c2 on c2.id = c.id where c2.change_set = %s and c.predicate = %s""",
                         (answers["mine"]["change_set"], FULFILLS)).fetchall()
        check(ref == [(f"file:{intent / 'catalogs' / 'mine.yaml'}",)],
              "the offer is referenced by what was read (a local repository: the catalog file that names it)")

        with planner_conn.cursor() as cur:
            request(cur, "urn:kk:request:c2")
        validator.drain(val)
        again = one_pass(rl, intent)["urn:kk:request:c2"]["answers"]
        check(any("already a candidate" in a.get("refused", "") for a in again if a["catalog"] == "mine")
              and not (intent / "experiments" / experiment_id(f"urn:kk:request:c2|{RECENT}")).exists(),
              "a provider already a candidate is not copied into a second experiment (one directory per provider id)")

        # The planner takes a catalog candidate as it takes the builder's: measured by the sandbox (the evaluator's
        # claims, written here as the evaluator), better than the incumbent and within the limit -> a replace plan.
        def measure(run_, provider, passed, mean):
            subj = f"urn:kk:eval:sandbox-analyser:{run_}"
            ops = [{"op": "add_claim", "subject": subj, "predicate": DCT + "subject", "object": {"entity": provider},
                    "evidence_type": "deterministic", "references": [{"source_uri": "urn:kk:test:sandbox"}]}]
            for k, v in (("contract.passed", passed), ("contract.total", 29), ("metric.mean", mean)):
                ops.append({"op": "add_claim", "subject": subj, "predicate": "http://www.w3.org/ns/dqv#value",
                            "object": {"value": {"@value": v}}, "evidence_type": "observed",
                            "qualifiers": {"http://www.w3.org/ns/dqv#isMeasurementOf": f"urn:kk:metric:sandbox-analyser:{k}"},
                            "references": [{"source_uri": "urn:kk:test:sandbox"}]})
            with ev.cursor() as cur, run(cur, "urn:kk:module:evaluator") as (rid, _):
                submit(cur, {"idempotency_key": f"test:{subj}", "attributed_to": "urn:kk:agent:evaluator",
                             "target_scope": "urn:kk:scope:default", "ops": ops}, rid)
        with planner_conn.cursor() as cur:
            check(planner.replace_for(cur, {"iri": "urn:kk:request:c1", "target": "urn:kk:provider:anomaly", "slot": "analyser",
                                            "claim_ids": [], "limit": None}, lambda risk: "review").get("wait"),
                  "the planner waits while the catalog candidate is unmeasured")
        measure(f"{exp_id}-incumbent", "urn:kk:provider:anomaly", 29, 0.9)
        measure(f"{exp_id}-candidate", RECENT, 29, 0.3)
        with planner_conn.cursor() as cur, run(cur, "urn:kk:module:planner") as (rid, _):
            submit(cur, {"idempotency_key": "test:limit", "attributed_to": "urn:kk:agent:planner", "target_scope": "urn:kk:scope:default",
                               "ops": [{"op": "add_claim", "subject": "urn:kk:provider:anomaly", "predicate": MAX,
                                        "object": {"value": {"@value": 0.5}}, "evidence_type": "testimony",
                                        "qualifiers": {"http://www.w3.org/ns/sosa/observedProperty": "urn:kk:property:step-seconds-mean"},
                                        "references": [{"source_uri": "urn:kk:test:limit"}]}]}, rid)
        validator.drain(val)
        with planner_conn.cursor() as cur:
            limit = planner.rows(cur, f"select {planner.COLUMNS} from api.claims where predicate = %s", (MAX,))[0]
            req_ids = [r[0] for r in cur.execute("select id::text from api.claims where subject = 'urn:kk:request:c1'").fetchall()]
            got = planner.replace_for(cur, {"iri": "urn:kk:request:c1", "target": "urn:kk:provider:anomaly", "slot": "analyser",
                                            "claim_ids": req_ids, "limit": limit}, lambda risk: "review")
        validator.drain(val)
        ops = su.execute("select ops from kernel.change_set where id = %s", (got.get("change_set"),)).fetchone()
        check(got.get("lane") == "review" and ops and any(
                  o["predicate"].endswith("substitutedBy") and o["object"] == {"entity": RECENT}
                  and tree_sha in (o.get("qualifiers") or {}).values() for o in ops[0]),
              "the planner turns a measured catalog candidate into a replace plan in the review lane, naming its content hash")

        spoof = search(rl, intent, "bike-parts", {"terms": ["spoofed"]})
        check([f["entry"] for f in spoof["found"]] == ["urn:kk:component:bike-parts:urn-kk-provider-anomaly"],
              "an entry of a components catalog cannot speak for a provider (its IRI is the catalog's, whatever it claims)")
        out = search(rl, intent, "bike-parts", {"terms": ["chainring"]})
        validator.drain(val)
        rows = rl.execute("""select subject, predicate, object_entity from api.claims
                             where subject like 'urn:kk:component:bike-parts:%%' and status <> 'deprecated'""").fetchall()
        check(len(out["found"]) == 1
              and ("urn:kk:component:bike-parts:chainring-52t", DCT + "isPartOf", "urn:kk:catalog:bike-parts") in rows
              and ("urn:kk:component:bike-parts:chainring-52t", DCT + "type", "urn:kk:component-kind:part") in rows
              and not any(p == FULFILLS for _, p, _ in rows),
              "a search of a component set outside software records its entry, applied without review, in the catalog, offering it for nothing")
        n = su.execute("select count(*) from kernel.change_set where attributed_to = %s", (AGENT,)).fetchone()[0]
        search(rl, intent, "bike-parts", {"terms": ["chainring"]})
        check(su.execute("select count(*) from kernel.change_set where attributed_to = %s", (AGENT,)).fetchone()[0] == n,
              "the same search again submits nothing new")
        check("refused" in search(rl, intent, "no-such", {}), "an unknown catalog is refused")
    shutil.rmtree(tmp)
    subprocess.run(["dropdb", "--if-exists", DB], check=True)
    print("registry-lookup service checks passed")


if __name__ == "__main__":
    main()
