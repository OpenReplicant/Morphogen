"""Builder checks: a build request becomes one committed experiment with a candidate of the slot, recorded
as claims citing the request; the fixture and harness strategies; requests it cannot serve are failed
runs, tried once.

  PGHOST=... PGUSER=<superuser> python3 tests/test_build.py
"""
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "src"), str(ROOT / "morphogen" / "modules"),
                str(ROOT / "kernel" / "providers" / "validator-shacl")]
from kk.lib import connect, run, submit  # noqa: E402
from builder.__main__ import AGENT, BUILD, DCT, OA, one_pass  # noqa: E402
from builder.build import build, check_candidate, experiment_id, incumbent_dir  # noqa: E402

install = importlib.import_module("install")
validator = importlib.import_module("validator.__main__")
DB = "kk_builder_test"
FIXTURES = ROOT / "morphogen" / "tests" / "fixtures"


def check(cond, msg):
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def request(cur, iri, target, slot="urn:kk:slot:analyser"):
    claim = lambda p, o: {"op": "add_claim", "subject": iri, "predicate": p, "object": o, "evidence_type": "testimony",
                          "references": [{"source_uri": "urn:kk:test:builder"}]}
    with run(cur, "urn:kk:module:planner") as (rid, _):
        submit(cur, {"idempotency_key": f"test:{iri}", "attributed_to": "urn:kk:agent:planner", "target_scope": "urn:kk:scope:default",
                     "ops": [claim(DCT + "type", {"entity": BUILD}), claim(OA + "hasTarget", {"entity": target}),
                             claim(DCT + "subject", {"entity": slot}),
                             claim(OA + "bodyValue", {"value": {"@value": "Make each pass read only the windows it compares."}})]}, rid)


def main() -> None:
    check(incumbent_dir("urn:kk:provider:anomaly") == ROOT / "morphogen" / "modules" / "anomaly"
          and incumbent_dir("urn:kk:provider:../x") is None and incumbent_dir("urn:kk:provider:nothing") is None,
          "the incumbent's directory comes from its provider id, and nothing else")
    bad = Path(tempfile.mkdtemp())
    shutil.copytree(ROOT / "morphogen" / "modules" / "anomaly", bad / "same", ignore=shutil.ignore_patterns("__pycache__"))
    try:
        check_candidate(bad / "same", "analyser", "urn:kk:provider:anomaly")
        check(False, "a candidate with the incumbent's id is refused")
    except ValueError:
        check(True, "a candidate with the incumbent's id is refused")

    # The harness strategy with a stand-in harness: it renames the provider, as a real one is asked to.
    exps = Path(tempfile.mkdtemp())
    script = bad / "harness.py"
    script.write_text("import sys, pathlib\np = pathlib.Path(sys.argv[1]) / 'provider.yaml'\n"
                      "p.write_text(p.read_text().replace('urn:kk:provider:anomaly', 'urn:kk:provider:anomaly-h'))\n"
                      "assert 'analyser' in sys.argv[2]\n")
    got = build({"iri": "urn:kk:request:h", "text": "faster"}, "analyser", ROOT / "morphogen" / "modules" / "anomaly", exps,
                "harness", command=f"{sys.executable} {script} {{workdir}} {{prompt}}")
    check(got["provider"] == "urn:kk:provider:anomaly-h" and (got["dir"] / "prompt.md").exists()
          and "tests/contract.py" in (got["dir"] / "prompt.md").read_text(),
          "harness: the incumbent copied, the harness run on it with a prompt naming the contract")

    subprocess.run(["dropdb", "--if-exists", DB], check=True)
    install.install(DB, install.modules())
    url = f"dbname={DB}"
    tmp = Path(tempfile.mkdtemp())
    intent = tmp / "intent"
    shutil.copytree(ROOT / "morphogen" / "intent", intent)
    g = lambda *a: subprocess.run(["git", "-C", str(intent), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                  check=True, capture_output=True, text=True).stdout
    g("init", "-q")
    g("add", "-A")
    g("commit", "-qm", "intent")
    with connect("kkm_planner", url) as planner, connect("kkm_validator", url) as val, connect("kkm_builder", url) as b:
        with planner.cursor() as cur:
            request(cur, "urn:kk:request:r1", "urn:kk:provider:anomaly")
            request(cur, "urn:kk:request:r2", "urn:kk:provider:no-such-provider")
        validator.drain(val)
        report = one_pass(b, intent, "fixture", FIXTURES, None)
        check(report["urn:kk:request:r1"]["status"] == "built" and report["urn:kk:request:r2"]["status"] == "failed",
              "a request is built; one naming no provider is a failed run")
        exp = intent / "experiments" / experiment_id("urn:kk:request:r1")
        check((exp / "experiment.yaml").exists() and (exp / "anomaly-recent" / "provider.yaml").exists()
              and "slot: analyser" in (exp / "experiment.yaml").read_text(), "the experiment: its description and the candidate")
        msg = g("log", "-1", "--format=%B")
        check(msg.startswith("request:urn:kk:request:r1 experiment:") and g("status", "--porcelain") == "",
              "one commit to intent, naming the request")
        validator.drain(val)
        rows = b.execute("""select predicate, object_entity, attributed_to from api.claims
                            where subject = 'urn:kk:provider:anomaly-recent'""").fetchall()
        check(("http://purl.org/dc/terms/source", "urn:kk:request:r1", AGENT) in rows and len(rows) == 2,
              "the candidate is recorded, citing the request it answers")
        ref = b.execute("""select r.source_uri from api.claim_references r join api.claims c on c.id = r.claim_id
                           where c.subject = 'urn:kk:provider:anomaly-recent' limit 1""").fetchone()[0]
        check(ref.startswith("file:intent/experiments/") and "#sha256=" in ref, "referenced by its directory and content hash")
        check(one_pass(b, intent, "fixture", FIXTURES, None) == {}, "each request is tried once")
    shutil.rmtree(tmp)
    shutil.rmtree(exps)
    shutil.rmtree(bad)


if __name__ == "__main__":
    main()
