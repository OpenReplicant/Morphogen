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
from morphogen import confine  # noqa: E402

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

    shutil.copytree(ROOT / "morphogen" / "modules" / "anomaly", bad / "grants", ignore=shutil.ignore_patterns("__pycache__"))
    (bad / "grants" / "provider.yaml").write_text((bad / "grants" / "provider.yaml").read_text().replace("provider:anomaly", "provider:anomaly-g"))
    (bad / "grants" / "migration.sql").write_text("grant kkm_evaluator to kkm_anomaly;\n")
    try:
        check_candidate(bad / "grants", "analyser", "urn:kk:provider:anomaly", ROOT / "morphogen" / "modules" / "anomaly")
        check(False, "a candidate with a migration of its own is refused")
    except ValueError:
        check(True, "a candidate with a migration of its own is refused")

    # The harness strategy with a stand-in harness: it renames the provider, as a real one is asked to, in a
    # directory outside intent, as the run user, with only the variables it was allowed.
    home = Path(tempfile.mkdtemp())
    subprocess.run(["git", "-C", str(home), "init", "-q"], check=True)
    home.chmod(0o777)                                    # writable by the run user: the git check must catch it
    exps = home / "experiments"
    with confine.workspace() as ws:
        script = ws / "harness.py"
        script.write_text("import os, sys, pathlib\np = pathlib.Path(sys.argv[1]) / 'provider.yaml'\n"
                          "p.write_text(p.read_text().replace('urn:kk:provider:anomaly', 'urn:kk:provider:anomaly-h'))\n"
                          "assert 'analyser' in sys.argv[2] and 'experiments' not in sys.argv[1]\n"
                          "assert not any(k == 'DATABASE_URL' or k.startswith(('PG', 'KK_')) for k in os.environ)\n"
                          "assert os.environ.get('HARNESS_KEY') == 'k' and 'OTHER_SECRET' not in os.environ\n"
                          "assert os.getuid() != 0, 'runs as root'\n"
                          "try:\n    pathlib.Path(f'/proc/{os.getppid()}/environ').read_bytes(); sys.exit('read its parent')\n"
                          "except PermissionError:\n    pass\n"
                          "if len(sys.argv) > 3: pathlib.Path(sys.argv[3]).write_text('x')\n")
        script.chmod(0o644)
        os.environ.update(DATABASE_URL="dbname=secret", HARNESS_KEY="k", OTHER_SECRET="s", KK_BUILDER_ENV="HARNESS_KEY")
        run_as = os.environ.pop("KK_RUN_AS")
        try:
            build({"iri": "urn:kk:request:h0", "text": "faster"}, "analyser", ROOT / "morphogen" / "modules" / "anomaly", exps,
                  "harness", command=f"{sys.executable} {script} {{workdir}} {{prompt}}")
            check(False, "the harness runs without an OS user of its own")
        except confine.Unconfined:
            check(True, "without KK_RUN_AS the harness does not run")
        os.environ["KK_RUN_AS"] = run_as
        with connect(url="dbname=postgres") as su:
            roles = confine.login_roles(su)
        got = build({"iri": "urn:kk:request:h", "text": "faster"}, "analyser", ROOT / "morphogen" / "modules" / "anomaly", exps,
                    "harness", command=f"{sys.executable} {script} {{workdir}} {{prompt}}", roles=roles)
        check(got["provider"] == "urn:kk:provider:anomaly-h" and (got["dir"] / "prompt.md").exists()
              and "runner.py" in (got["dir"] / "prompt.md").read_text(),
              f"harness: run as {run_as} on a copy of the incumbent outside intent, with only the variables KK_BUILDER_ENV "
              "names, unable to read its parent's environment, with a prompt naming the slot's runner")
        try:
            build({"iri": "urn:kk:request:h2", "text": "faster"}, "analyser", ROOT / "morphogen" / "modules" / "anomaly", exps,
                  "harness", command=f"{sys.executable} {script} {{workdir}} {{prompt}} {home / 'stray.txt'}")
            check(False, "a harness that writes outside its workdir fails the build")
        except RuntimeError as e:
            check("outside its workdir" in str(e) and not (exps / experiment_id("urn:kk:request:h2")).exists(),
                  "a harness that writes outside its workdir fails the build")
    for k in ("DATABASE_URL", "HARNESS_KEY", "OTHER_SECRET", "KK_BUILDER_ENV"):
        del os.environ[k]

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
