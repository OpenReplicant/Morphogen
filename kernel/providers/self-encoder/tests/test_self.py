"""The record answers "which provider fills each slot" with citations (T4).

A copy of the kernel's blueprint and provider manifests, plus a small distribution, is scanned into a fresh
record (pack loader, validator, self-encoder). Then, for every slot in the blueprint, the answer names the
providers whose manifests say they fill it, or says why it is unfilled, and every part cites a claim whose
reference is the file and line where that is written. Scanning again is a no-op; a changed manifest
supersedes its claims; a removed one retracts them.

  PGHOST=... PGUSER=<superuser> python3 kernel/providers/self-encoder/tests/test_self.py
"""
import importlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
PROVIDERS = HERE.parents[1]
KERNEL = PROVIDERS.parent
for p in (KERNEL / "src", PROVIDERS, PROVIDERS / "validator-shacl", PROVIDERS / "self-encoder"):
    sys.path.insert(0, str(p))

import install  # noqa: E402
from kk.lib import connect  # noqa: E402

validator = importlib.import_module("validator.__main__")
encoder = importlib.import_module("self_encoder.__main__")
DB = "kk_self_test"


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}")


def make_repo() -> Path:
    repo = Path(tempfile.mkdtemp())
    (repo / "kernel" / "blueprint").mkdir(parents=True)
    shutil.copy(KERNEL / "blueprint" / "slots.yaml", repo / "kernel" / "blueprint" / "slots.yaml")
    for manifest in PROVIDERS.glob("*/provider.yaml"):
        if not manifest.parent.name.startswith("_"):
            (repo / "kernel" / "providers" / manifest.parent.name).mkdir(parents=True)
            shutil.copy(manifest, repo / "kernel" / "providers" / manifest.parent.name / "provider.yaml")
    (repo / "dist").mkdir()
    shutil.copy(HERE / "fixtures" / "distribution.yaml", repo / "dist" / "distribution.yaml")
    return repo


def cited_line(repo: Path, source: list[str]) -> str:
    """The text of the line a citation names (file:<rel>#line=N)."""
    m = re.fullmatch(r"file:(.+)#line=(\d+)", source[0])
    return (repo / m.group(1)).read_text().splitlines()[int(m.group(2)) - 1]


def scan_and_apply(repo: Path) -> list[dict]:
    out = encoder.scan(repo, [str(repo / "dist" / "distribution.yaml")])
    with connect("kkm_validator", f"dbname={DB}") as val:
        validator.drain(val)
    return out


def main() -> None:
    import os
    subprocess.run(["dropdb", "--if-exists", "--force", DB], check=True)
    install.install(DB, ["pack-loader", "validator-shacl", "self-encoder"])
    os.environ["DATABASE_URL"] = f"dbname={DB}"
    repo = make_repo()
    first = scan_and_apply(repo)
    with connect("kkm_self_encoder", f"dbname={DB}") as conn:
        check(len(first) == len({r["file"] for r in first}) == 1 + len(list(repo.glob("kernel/providers/*/provider.yaml"))) + 1,
              "scan submits one change set per file: the blueprint, each manifest, the distribution")
        applied = {r[0] for r in conn.execute("select id::text from api.change_sets where status = 'applied'")}
        check(all(r["change_set"] in applied for r in first),
              f"every file's change set is validated and applied ({len(first)} files)")

        blueprint = yaml.safe_load((repo / "kernel/blueprint/slots.yaml").read_text())["slots"]
        manifests = {p.parent.name: yaml.safe_load(p.read_text())["slots"] for p in repo.glob("kernel/providers/*/provider.yaml")}
        answers = {a["slot"]: a for a in encoder.answer(conn)}
        for slot in blueprint:
            a = answers.get(f"urn:kk:slot:{slot['id']}")
            if a is None:
                raise SystemExit(f"CHECK FAILED: no answer for {slot['id']}")
            if slot["id"] not in cited_line(repo, a["declared"]["source"]):
                raise SystemExit(f"CHECK FAILED: {slot['id']} cites {a['declared']['source']}")
            want = sorted(f"urn:kk:provider:{n}" for n, slots in manifests.items() if slot["id"] in slots)
            got = sorted(f["provider"] for f in a["filled_by"])
            if got != want or any(not cited_line(repo, f["source"]).startswith("slots:") for f in a["filled_by"]):
                raise SystemExit(f"CHECK FAILED: {slot['id']}: filled by {got}, manifests say {want}")
            if slot.get("default") == "none" and not (a.get("note", {}).get("text", "").startswith("Unfilled")
                                                      and "why:" in cited_line(repo, a["note"]["source"])):
                raise SystemExit(f"CHECK FAILED: {slot['id']} is unfilled but the answer does not say why")
        check(True, f"all {len(blueprint)} blueprint slots answered: filled by what the manifests say, each part cited "
                    "to its file and line")
        check(answers["urn:kk:slot:record-store"]["filled_by"][0]["provider"] == "urn:kk:provider:record-postgres"
              and not answers["urn:kk:slot:truth-maintenance"]["filled_by"],
              "record-store is filled by record-postgres; truth-maintenance is unfilled, with why")
        check("urn:kk:slot:observer" in answers and not answers["urn:kk:slot:observer"]["filled_by"]
              and "observer-otel" in answers["urn:kk:slot:observer"]["note"]["text"],
              "a distribution's application slot is recorded with its intended default")
        part = conn.execute("select count(*) from api.claims where subject = 'urn:kk:distribution:demo' and "
                            "predicate = 'http://purl.org/dc/terms/hasPart' and status <> 'deprecated'").fetchone()[0]
        check(part == 3, "the distribution has its kernel slots and application slots as parts")

    again = scan_and_apply(repo)
    check([r["change_set"] for r in again] == [r["change_set"] for r in first], "scanning unchanged files again is a no-op")

    m = repo / "kernel/providers/evaluator/provider.yaml"
    m.write_text(m.read_text().replace("version: 0.1.0", "version: 0.1.1"))
    shutil.rmtree(repo / "kernel/providers/verifier-quotes")
    scan_and_apply(repo)
    with connect("kkm_self_encoder", f"dbname={DB}") as conn:
        versions = conn.execute("select object_value->>'@value', status from api.claims where subject = "
                                "'urn:kk:provider:evaluator' and predicate like '%versionInfo' order by 1").fetchall()
        check(versions == [("0.1.0", "deprecated"), ("0.1.1", "normal")], "a changed manifest supersedes its claims")
        answers = {a["slot"]: a for a in encoder.answer(conn, ["verifier"])}
        check(answers["urn:kk:slot:verifier"]["filled_by"] == [], "a removed provider no longer fills its slot")
    subprocess.run(["dropdb", "--force", DB], check=True)
    print("ALL SELF-ENCODER TESTS PASSED")


if __name__ == "__main__":
    main()
