import copy
import json
import subprocess
from pathlib import Path

import pytest

from judge import admit

ROOT = Path(__file__).resolve().parent.parent
CARD = json.loads((ROOT / "examples/card.json").read_text())
POLICY = json.loads((ROOT / "examples/policy.json").read_text())


def change(path, mode="100644", status="M"):
    return {"path": path, "mode": mode, "status": status}


def test_an_in_scope_change_is_admitted():
    assert admit.admit(CARD, POLICY, [change("topwords/core.py")]) == []


@pytest.mark.parametrize("path", [
    "tests/test_topwords.py", ".gitea/workflows/judge.yml", ".github/workflows/x.yml", ".morphogen/policy.json",
    "topwords/sitecustomize.py", "topwords/evil.pth", ".gitattributes", "pyproject.toml", "README.md",
    "topwords/data.txt",  # in the policy's scope but not the card's (*.py)
])
def test_out_of_scope_or_protected_paths_are_refused(path):
    assert admit.admit(CARD, POLICY, [change("topwords/core.py"), change(path)])


def test_links_and_submodules_are_refused():
    assert admit.admit(CARD, POLICY, [change("topwords/core.py", mode="120000")])
    assert admit.admit(CARD, POLICY, [change("topwords/core.py", mode="160000")])


def test_an_empty_change_is_refused():
    assert admit.admit(CARD, POLICY, [])


@pytest.mark.parametrize("edit", [
    lambda c: c["kpis"].pop(0),                                   # drop the deciding KPI
    lambda c: c["kpis"].pop(1),                                   # drop the bound
    lambda c: c["kpis"][1].update(floor=5.0),                     # loosen the bound
    lambda c: c["kpis"][0].update(role="bound"),                  # demote the deciding KPI
    lambda c: c["kpis"][0].update(direction="lower"),
    lambda c: c["kpis"][0].update(source="runner"),
    lambda c: c["kpis"].append({"name": "vibes", "source": "scorer", "direction": "higher", "floor": 0, "role": "decide"}),
    lambda c: c["cases"].update(set="easy-cases"),                # a set the policy does not list
    lambda c: c.update(network=["pypi.org"]),
    lambda c: c.update(card="morphogen.card/v0"),
])
def test_cards_that_widen_the_policy_are_refused(edit):
    c = copy.deepcopy(CARD)
    edit(c)
    assert admit.admit(c, POLICY, [change("topwords/core.py")])


def test_a_card_may_be_stricter():
    c = copy.deepcopy(CARD)
    c["kpis"][0]["floor"] = 0.1
    c["kpis"][1]["floor"] = 0.1
    c["scope"] = ["topwords/core.py"]
    assert admit.admit(c, POLICY, [change("topwords/core.py")]) == []


def test_glob_semantics():
    assert admit.matches("a/b/c.py", ["a/**"])
    assert admit.matches("a/c.py", ["a/**/c.py"])
    assert not admit.matches("a/b/c.py", ["a/*.py"])
    assert not admit.matches("ab/c.py", ["a/**"])
    assert admit.matches("x/y/sitecustomize.py", ["**/sitecustomize.py"])
    assert admit.matches("sitecustomize.py", ["**/sitecustomize.py"])


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def test_changes_come_from_git(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@t"); git(tmp_path, "config", "user.name", "t")
    (tmp_path / "topwords").mkdir()
    (tmp_path / "topwords/core.py").write_text("x = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/t.py").write_text("pass\n")
    git(tmp_path, "add", "."); git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "checkout", "-qb", "cand")
    (tmp_path / "topwords/core.py").unlink()
    (tmp_path / "topwords/core.py").symlink_to("../tests/t.py")
    git(tmp_path, "mv", "tests/t.py", "topwords/t.py")
    git(tmp_path, "add", "-A"); git(tmp_path, "commit", "-qm", "cand")
    got = {(c["path"], c["mode"], c["status"]) for c in admit.changes(tmp_path, "main", "cand")}
    assert ("topwords/core.py", "120000", "T") in got
    assert ("tests/t.py", "000000", "D") in got            # a rename is a delete it must be allowed to make
    reasons = admit.admit(CARD, POLICY, admit.changes(tmp_path, "main", "cand"))
    assert any("symbolic link" in r for r in reasons) and any("tests/t.py" in r for r in reasons)


# A change is judged when it touches the policy's scope. Every other change gets an unjudged pass,
# unless it touches what the judge relies on: those are a person's to merge, never the judge's.

@pytest.mark.parametrize("paths", [["README.md"], ["docs/x.md", "src/other.py"], []])
def test_a_change_outside_the_policy_scope_is_not_judged(paths):
    judged, reasons = admit.triage(POLICY, [change(p) for p in paths])
    assert (judged, reasons) == (False, [])


@pytest.mark.parametrize("path", [
    ".github/workflows/forge.yml", ".morphogen/policy.json", ".morphogen/scorer.py", "tests/test_topwords.py",
    "docs/sitecustomize.py", "x.pth", ".gitattributes",
])
def test_an_unjudged_change_to_what_the_judge_relies_on_is_refused(path):
    judged, reasons = admit.triage(POLICY, [change("README.md"), change(path)])
    assert not judged and reasons and "a person's to merge" in reasons[0]


def test_an_unjudged_link_or_submodule_is_refused():
    assert admit.triage(POLICY, [change("README.md", mode="120000")])[1]
    assert admit.triage(POLICY, [change("vendor/x", mode="160000")])[1]


def test_touching_the_scope_makes_the_whole_change_judged():
    judged, _ = admit.triage(POLICY, [change("README.md"), change("topwords/core.py")])
    assert judged
    # and then the usual admission applies to every path, README included
    assert admit.admit(CARD, POLICY, [change("README.md"), change("topwords/core.py")])


def test_moving_a_file_out_of_scope_is_judged():
    # --no-renames: a move is a delete inside the scope plus an add outside it
    judged, _ = admit.triage(POLICY, [change("topwords/core.py", status="D"), change("elsewhere/core.py", status="A")])
    assert judged


def test_main_writes_an_unjudged_admission(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("a\n")
    git(repo, "add", "-A"); git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "a")
    git(repo, "checkout", "-qb", "c")
    (repo / "README.md").write_text("b\n")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "b")
    pol = tmp_path / "policy.json"
    pol.write_text(json.dumps(POLICY))
    out = tmp_path / "adm.json"
    monkeypatch.setenv("PR_BODY", "no card here")
    assert admit.main(["--repo", str(repo), "--base", "main", "--head", "c", "--policy", str(pol), "--card-out", str(out)]) == 0
    assert json.loads(out.read_text()) == {"card": None, "refused": [], "judged": False}
