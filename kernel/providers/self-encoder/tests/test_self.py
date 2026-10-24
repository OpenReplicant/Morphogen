"""The record answers "which provider fills each slot" with citations (T4).

A copy of the kernel's blueprint and provider manifests, plus a small distribution, is scanned into a fresh
record (pack loader, validator, self-encoder). Then, for every slot in the blueprint, the answer names the
providers whose manifests say they fill it, or says why it is unfilled, and every part cites a claim whose
reference is the file and line where that is written, with its belief. Scanning again is a no-op; a
changed manifest supersedes its claims, and so does one reverted to earlier content; a removed one is
retracted and a restored one comes back; a distribution is retracted only with --forget.

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
for p in (KERNEL / "src", PROVIDERS, PROVIDERS / "validator-shacl", PROVIDERS / "belief-corroboration",
          PROVIDERS / "self-encoder"):
    sys.path.insert(0, str(p))

import install  # noqa: E402
from kk.lib import connect, follow  # noqa: E402

validator = importlib.import_module("validator.__main__")
encoder = importlib.import_module("self_encoder.__main__")
belief = importlib.import_module("belief_corroboration.__main__")
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


def scan_and_apply(repo: Path, distribution: bool = True, forget: bool = False, providers: list[str] = ()) -> list[dict]:
    dist = [str(repo / "dist" / "distribution.yaml")]
    out = encoder.scan(repo, dist if distribution else [], dist if forget else [], providers)
    with connect("kkm_validator", f"dbname={DB}") as val:
        validator.drain(val)
        with connect("kkm_belief", f"dbname={DB}") as bel:
            follow(bel, belief.Pass(), once=True)
        validator.drain(val)
    return out


def versions(conn) -> list:
    return conn.execute("select object_value->>'@value', status from api.claims where subject = "
                        "'urn:kk:provider:evaluator' and predicate like '%%versionInfo' order by recorded_at").fetchall()


def current_version(conn) -> list:
    return [v for v, st in versions(conn) if st != "deprecated"]


def fills(conn, slot: str) -> list:
    return [f["provider"] for f in encoder.answer(conn, [slot])[0]["filled_by"]]


def main() -> None:
    import os
    subprocess.run(["dropdb", "--if-exists", "--force", DB], check=True)
    install.install(DB, ["pack-loader", "validator-shacl", "belief-corroboration", "self-encoder"])
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
            if a is None or a["declared"] is None:
                raise SystemExit(f"CHECK FAILED: no answer for {slot['id']}")
            if slot["id"] not in cited_line(repo, a["declared"]["source"]):
                raise SystemExit(f"CHECK FAILED: {slot['id']} cites {a['declared']['source']}")
            want = sorted(f"urn:kk:provider:{n}" for n, slots in manifests.items() if slot["id"] in slots)
            got = sorted(f["provider"] for f in a["filled_by"])
            if got != want or any(not cited_line(repo, f["source"]).startswith("slots:") for f in a["filled_by"]):
                raise SystemExit(f"CHECK FAILED: {slot['id']}: filled by {got}, manifests say {want}")
            note_line = cited_line(repo, a["note"]["source"])
            if slot.get("default") == "none":
                ok = a["note"]["text"].startswith("Unfilled") and "why:" in note_line
            else:
                ok = a["note"]["text"].startswith("Default provider") and f"default: {slot['default']}" in note_line
            if not ok:
                raise SystemExit(f"CHECK FAILED: {slot['id']}: note {a['note']} cites {note_line!r}")
            parts = [a["declared"], a["note"], *a["filled_by"]]
            if any(p["belief"] is None for p in parts):
                raise SystemExit(f"CHECK FAILED: {slot['id']}: an unscored claim in the answer")
        check(True, f"all {len(blueprint)} blueprint slots answered: filled by what the manifests say, the default or "
                    "why unfilled, every part cited to its file and line and shown with its belief")
        check(answers["urn:kk:slot:record-store"]["filled_by"][0]["provider"] == "urn:kk:provider:record-postgres"
              and not answers["urn:kk:slot:truth-maintenance"]["filled_by"],
              "record-store is filled by record-postgres; truth-maintenance is unfilled, with why")
        check("observer-otel" in answers["urn:kk:slot:observer"]["note"]["text"]
              and not answers["urn:kk:slot:observer"]["filled_by"],
              "a distribution's application slot is recorded with its intended default")
        parts = conn.execute("select object_entity, id::text from api.claims where subject = 'urn:kk:distribution:demo' "
                             "and predicate = 'http://purl.org/dc/terms/hasPart' and status <> 'deprecated'").fetchall()
        check(len(parts) == 3 and all(e.rsplit(":", 1)[1] in cited_line(repo, encoder.cite(conn, i)["source"])
                                      for e, i in parts),
              "the distribution has its kernel and application slots as parts, each cited to its line")
        check(encoder.answer(conn, ["no-such-slot"])[0]["declared"] is None, "a slot not in the record says so")

    again = scan_and_apply(repo)
    check(all(r["status"] == "unchanged" for r in again), "scanning unchanged files again is a no-op")
    scan_and_apply(repo, distribution=False)
    with connect("kkm_self_encoder", f"dbname={DB}") as conn:
        check(len(encoder.answer(conn, ["observer"])[0]["filled_by"]) == 0
              and encoder.answer(conn, ["observer"])[0]["declared"] is not None,
              "a scan without the distribution leaves the distribution's claims alone")

    m = repo / "kernel/providers/evaluator/provider.yaml"
    original = m.read_text()
    m.write_text(original.replace("version: 0.1.0", "version: 0.1.1"))
    scan_and_apply(repo)
    with connect("kkm_self_encoder", f"dbname={DB}") as conn:
        check(current_version(conn) == ["0.1.1"], "a changed manifest supersedes its claims")
    m.write_text(original)
    scan_and_apply(repo)
    with connect("kkm_self_encoder", f"dbname={DB}") as conn:
        check(current_version(conn) == ["0.1.0"], "a manifest reverted to earlier content is recorded again (A-B-A)")

    kept = (repo / "kernel/providers/verifier-quotes/provider.yaml").read_text()
    shutil.rmtree(repo / "kernel/providers/verifier-quotes")
    scan_and_apply(repo)
    with connect("kkm_self_encoder", f"dbname={DB}") as conn:
        reasons = {r[0] for r in conn.execute(
            "select s.reason from kernel.claim_status s join api.claims c on c.id = s.claim_id "
            "where c.subject = 'urn:kk:provider:verifier-quotes'").fetchall()}
        check(fills(conn, "verifier") == [] and reasons == {"retracted"},
              "a removed provider's claims are retracted, and it no longer fills its slot")
        check(fills(conn, "record-store") == ["urn:kk:provider:record-postgres"], "other files' claims are untouched")
    (repo / "kernel/providers/verifier-quotes").mkdir()
    (repo / "kernel/providers/verifier-quotes/provider.yaml").write_text(kept)
    scan_and_apply(repo)
    with connect("kkm_self_encoder", f"dbname={DB}") as conn:
        check(fills(conn, "verifier") == ["urn:kk:provider:verifier-quotes"], "a restored provider fills its slot again")

    # A distribution's own providers (--providers DIR): recorded like the kernel's; left alone by a scan that
    # was not given the directory; retracted when the directory is scanned and the provider is gone.
    mine = repo / "dist" / "modules" / "watcher"
    mine.mkdir(parents=True)
    (mine / "provider.yaml").write_text("id: urn:kk:provider:watcher\nname: Watcher\nversion: 0.1.0\n"
                                        "license: Apache-2.0\nslots: [observer]\n")
    extra = [str(repo / "dist" / "modules")]
    scan_and_apply(repo, providers=extra)
    with connect("kkm_self_encoder", f"dbname={DB}") as conn:
        got = encoder.answer(conn, ["observer"])[0]["filled_by"]
        check([f["provider"] for f in got] == ["urn:kk:provider:watcher"]
              and cited_line(repo, got[0]["source"]) == "slots: [observer]",
              "a provider under --providers fills its distribution's slot, cited to its manifest's line")
    scan_and_apply(repo)
    with connect("kkm_self_encoder", f"dbname={DB}") as conn:
        check(fills(conn, "observer") == ["urn:kk:provider:watcher"], "a scan not given the directory leaves its providers alone")
    shutil.rmtree(mine)
    scan_and_apply(repo, providers=extra)
    with connect("kkm_self_encoder", f"dbname={DB}") as conn:
        check(fills(conn, "observer") == [], "a provider gone from a directory scanned again is retracted")

    scan_and_apply(repo, distribution=False, forget=True)
    with connect("kkm_self_encoder", f"dbname={DB}") as conn:
        check(encoder.answer(conn, ["observer"])[0]["declared"] is None, "--forget retracts a distribution")
    subprocess.run(["dropdb", "--force", DB], check=True)
    print("ALL SELF-ENCODER TESTS PASSED")


if __name__ == "__main__":
    main()
