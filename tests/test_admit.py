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
