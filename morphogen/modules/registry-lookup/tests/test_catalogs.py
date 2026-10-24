"""Catalog checks (R5-30), no database: component sets of any kind are searched alike; every entry gets each rule's
verdict and an enforced rule withholds only the offer; PyPI-shaped records are read; a provider catalog at a pinned
commit gives that commit's content, not a later one's.

  python3 tests/test_catalogs.py   (needs git)
"""
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "morphogen" / "src")]
from morphogen.experiments import tree_hash  # noqa: E402

from registry_lookup import catalogs as c  # noqa: E402


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg)


NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)
parts = {"name": "bike-parts", "kind": "components", "components": [
    {"id": "chainring-52t", "label": "Chainring, 52 teeth", "kind": "part", "description": "road chainring, 130 mm BCD",
     "properties": {"material": "aluminium 7075", "teeth": 52}},
    {"id": "chain-11s", "label": "Chain, 11-speed", "kind": "part", "properties": {"speeds": 11}}]}
libs = {"name": "libs", "kind": "components", "components": [
    {"id": "psycopg", "label": "psycopg", "kind": "python-package", "version": "3.2.10", "licence": "LGPL-3.0",
     "published": "2025-09-08T10:00:00Z", "sha256": "ab5caf09"},
    {"id": "gplthing", "label": "gplthing", "kind": "python-package", "version": "1.0", "licence": "GPL-3.0-only",
     "published": "2026-10-20T10:00:00Z"}]}
found = c.search(parts, {"terms": ["chainring", "aluminium"]})
check([e["id"] for e in found] == ["chainring-52t"] and found[0]["kind"] == "part",
      "a component set outside software is searched like any other (a chainring by its material)")
check([e["id"] for e in c.search(libs, {"kind": "python-package"})] == ["psycopg", "gplthing"], "a software set, by kind")
rules = {"licences": {"enforce": False, "allow": ["Apache-2.0", "LGPL-3.0"]}, "pinned": {"enforce": False}}
v = {e["id"]: c.verdicts(e, rules, NOW) for e in c.search(libs, {})}
check(not v["gplthing"]["licences"]["ok"] and not v["gplthing"]["pinned"]["ok"]
      and all(x["ok"] for x in v["psycopg"].values()), "every entry gets each rule's verdict (licence, pinned)")
check([e["id"] for e in c.search(libs, {"min_age_days": 14, "now": NOW})] == ["psycopg"]
      and len(c.search(libs, {"min_age_days": 0, "now": NOW})) == 2,
      "a search setting, not a rule: releases newer than min_age_days are left out by default, all found with 0")
check(c.offer(v["gplthing"]), "rules not enforced: everything found is offered (open by default)")
on = {**rules, "licences": {**rules["licences"], "enforce": True}}
check(not c.offer(c.verdicts(c.search(libs, {"terms": ["gplthing"]})[0], on, NOW))
      and c.offer(c.verdicts(c.search(libs, {"terms": ["psycopg"]})[0], on, NOW)),
      "an enforced rule withholds the offer of the entry that fails it, and only that")

record = {"info": {"name": "psycopg", "version": "3.2.10", "summary": "PostgreSQL database adapter for Python",
                   "license": "GNU Lesser General Public License v3 (LGPLv3)", "requires_python": ">=3.8"},
          "urls": [{"upload_time_iso_8601": "2025-09-08T10:00:00.000000Z", "digests": {"sha256": "ab5c"}}]}
seen = []
fetch = lambda url: seen.append(url) or (record if url.endswith("/psycopg/json") else (_ for _ in ()).throw(OSError("404")))  # noqa: E731
got = c.pypi({"name": "pypi", "kind": "pypi", "index": "https://example.invalid/pypi"}, {"terms": ["psycopg", "nosuchproject"]}, fetch=fetch)
check(len(got) == 1 and got[0]["version"] == "3.2.10" and got[0]["pinned"] and "Lesser" in got[0]["licence"]
      and seen == ["https://example.invalid/pypi/psycopg/json", "https://example.invalid/pypi/nosuchproject/json"],
      "PyPI: named projects looked up in its JSON API; one that is not there is skipped")
check(got[0]["published"].startswith("2025-09-08") and c.verdicts(got[0], on, NOW)["licences"]["ok"],
      "PyPI: the release's upload time is kept and its licence read (LGPL by its name)")

tmp = Path(tempfile.mkdtemp())
try:
    repo = tmp / "repo"
    git = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@e", *a],  # noqa: E731
                                    check=True, capture_output=True, text=True).stdout.strip()
    shutil.copytree(ROOT / "morphogen" / "tests" / "fixtures" / "analyser" / "anomaly-recent", repo / "providers" / "anomaly-recent",
                    ignore=shutil.ignore_patterns("__pycache__"))
    repo.mkdir(exist_ok=True)
    git("init", "-q")
    git("add", "-A")
    git("commit", "-qm", "one")
    first = git("rev-parse", "HEAD")
    pinned_sha = tree_hash(repo / "providers" / "anomaly-recent")
    (repo / "providers" / "anomaly-recent" / "LATER").write_text("changed after the pin\n")
    git("add", "-A")
    git("commit", "-qm", "two")
    cat = {"name": "mine", "kind": "providers", "source": {"git": str(repo), "commit": first, "path": "providers"}}
    work = tmp / "work"
    work.mkdir()
    got = c.search(cat, {"slot": "analyser"}, workdir=work)
    check(len(got) == 1 and got[0]["sha256"] == pinned_sha and got[0]["pinned"] and "analyser" in got[0]["slots"]
          and not (Path(got[0]["path"]) / "LATER").exists(),
          "a provider catalog at a pinned commit gives that commit's content, not the later one")
    check(c.search(cat, {"slot": "planner"}) == [], "a provider that does not fill the slot asked for is not found")
    head = c.search({**cat, "source": {**cat["source"], "commit": "master"}}, {"slot": "analyser"})
    check(head and not head[0]["pinned"], "a branch name is not a pin")
    for bad in ({"git": str(repo), "commit": first, "path": "../.."}, {"dir": "../.."}):
        try:
            c.search({"name": "esc", "kind": "providers", "source": bad}, {})
            check(False, f"a source that leaves its repository is refused ({bad})")
        except ValueError:
            check(True, f"a source that leaves its repository is refused ({list(bad)[-1]})")
    spoof = c.search({"name": "parts", "kind": "components", "components": [
        {"id": "urn:kk:provider:anomaly", "kind": "provider", "catalog": "mine", "pinned": True}]}, {})
    check(spoof[0]["catalog"] == "parts" and spoof[0]["adapter"] == "components" and not spoof[0]["pinned"],
          "a components entry cannot name another catalog, pose as a provider catalog's entry, or call itself pinned without a hash")
    local = {"name": "local", "kind": "providers", "source": {"dir": "morphogen/tests/fixtures/analyser"},
             "pins": {"urn:kk:provider:anomaly-recent": "0" * 64}}
    got = c.search(local, {"slot": "analyser"})
    check(got and not got[0]["pinned"] and "mismatch" in got[0], "a local provider whose content is not its stated hash is not pinned")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("catalog checks passed")
